import tempfile
import unittest
from pathlib import Path

from poi_evaluator.db import connect, initialize
from poi_evaluator.url_validator import HttpResponse, UrlCheckResult, UrlValidator, validate_urls


PUBLIC_IP = "93.184.216.34"


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs["approved_ip"]))
        return self.responses.pop(0)


def public_resolver(hostname, port):
    return [PUBLIC_IP]


class UrlValidatorTests(unittest.TestCase):
    def test_private_address_is_blocked_before_transport(self):
        transport = FakeTransport([])
        validator = UrlValidator(transport=transport, resolver=lambda host, port: ["127.0.0.1"])
        result = validator.check("http://internal.example/admin")
        self.assertEqual(result.status, "invalid_url")
        self.assertEqual(result.error_code, "ssrf_blocked")
        self.assertEqual(transport.calls, [])

    def test_head_falls_back_to_get(self):
        transport = FakeTransport(
            [
                HttpResponse(405, {"content-type": "text/html"}),
                HttpResponse(200, {"content-type": "text/html; charset=utf-8"}),
            ]
        )
        validator = UrlValidator(transport=transport, resolver=public_resolver)
        result = validator.check("https://example.com/place")
        self.assertEqual(result.status, "reachable")
        self.assertEqual(result.request_method, "GET")
        self.assertEqual([call[0] for call in transport.calls], ["HEAD", "GET"])

    def test_redirect_is_recorded(self):
        transport = FakeTransport(
            [
                HttpResponse(301, {"location": "https://www.example.com/final", "content-type": "text/html"}),
                HttpResponse(200, {"content-type": "text/html"}),
            ]
        )
        validator = UrlValidator(transport=transport, resolver=public_resolver)
        result = validator.check("https://example.com/start")
        self.assertEqual(result.status, "redirected")
        self.assertEqual(result.final_url, "https://www.example.com/final")
        self.assertEqual(len(result.redirects), 1)

    def test_redirect_to_private_network_is_blocked(self):
        transport = FakeTransport(
            [HttpResponse(302, {"location": "http://127.0.0.1/secret", "content-type": "text/html"})]
        )

        def resolver(hostname, port):
            return ["127.0.0.1"] if hostname == "127.0.0.1" else [PUBLIC_IP]

        validator = UrlValidator(transport=transport, resolver=resolver)
        result = validator.check("https://example.com/start")
        self.assertEqual(result.status, "invalid_url")
        self.assertEqual(len(transport.calls), 1)

    def test_image_mime_mismatch(self):
        transport = FakeTransport([HttpResponse(200, {"content-type": "text/html"})])
        validator = UrlValidator(transport=transport, resolver=public_resolver)
        result = validator.check("https://example.com/not-an-image.jpg", "image")
        self.assertEqual(result.status, "mime_mismatch")

    def test_database_validation_deduplicates_and_resumes(self):
        class CountingValidator:
            def __init__(self):
                self.calls = 0

            def check(self, url, target_type="link"):
                self.calls += 1
                return UrlCheckResult(
                    url=url,
                    status="reachable",
                    request_method="HEAD",
                    http_status=200,
                    final_url=url,
                    content_type="text/html",
                )

        with tempfile.TemporaryDirectory() as directory:
            connection = connect(Path(directory) / "url-checks.sqlite")
            initialize(connection)
            submission_id = connection.execute(
                "INSERT INTO submissions(agent_name, source_path, source_sha256, raw_document_json) VALUES ('a', 'a.json', 'digest', '{}')"
            ).lastrowid
            for original_id in ("one", "two"):
                poi_id = connection.execute(
                    "INSERT INTO poi_records(submission_id, original_poi_id, name, normalized_name, raw_json, normalized_json) VALUES (?, ?, ?, ?, '{}', '{}')",
                    (submission_id, original_id, original_id, original_id),
                ).lastrowid
                connection.execute(
                    "INSERT INTO links(poi_record_id, link_type, url, raw_json) VALUES (?, 'reference', 'https://example.com/shared', '{}')",
                    (poi_id,),
                )
            first_run = connection.execute(
                "INSERT INTO evaluation_runs(run_type, status) VALUES ('url_validation', 'running')"
            ).lastrowid
            connection.commit()
            validator = CountingValidator()
            summary = validate_urls(
                connection, first_run, validator, workers=2, per_host=1
            )
            self.assertEqual(summary["checked"], 2)
            self.assertEqual(summary["unique_requests"], 1)
            self.assertEqual(validator.calls, 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM url_checks").fetchone()[0], 2)

            connection.execute(
                "INSERT INTO ratings(poi_record_id, provider, source_url, raw_json) VALUES (?, 'demo', 'https://example.com/shared', '{}')",
                (poi_id,),
            )

            second_run = connection.execute(
                "INSERT INTO evaluation_runs(run_type, status) VALUES ('url_validation', 'running')"
            ).lastrowid
            connection.commit()
            resumed = validate_urls(
                connection, second_run, validator, workers=2, per_host=1
            )
            self.assertEqual(resumed["checked"], 1)
            self.assertEqual(resumed["skipped_existing"], 2)
            self.assertEqual(resumed["unique_requests"], 0)
            self.assertEqual(resumed["reused_results"], 1)
            self.assertEqual(validator.calls, 1)
            connection.close()


if __name__ == "__main__":
    unittest.main()
