#!/usr/bin/env python3
"""Offline structural and minimum-coverage validator for Universal POI Discovery.

This is NOT a geographic, licensing, URL-reachability or fact-checking service.
"""
import argparse
import collections
import datetime
import json
import math
import pathlib
import re
import sys
from urllib.parse import urlparse

from jsonschema import Draft202012Validator, FormatChecker

ROOT = pathlib.Path(__file__).resolve().parents[1]


def load(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def compute_target(profile, config):
    target = config['target']
    if target['mode'] == 'fixed':
        return int(target['minimum'])
    if target['mode'] != 'adaptive':
        raise ValueError('Unsupported target mode')
    population = profile['demographics']['population']
    tourism = profile['tourism']['value']
    metric = profile['tourism']['metric']
    area = profile['geography']['areaKm2']
    if metric != 'visitor_arrivals' or any(v is None for v in (population, tourism, area)):
        raise ValueError('Adaptive mode requires verified population, visitor arrivals and area; no guessing')
    if any(v < 0 for v in (population, tourism, area)):
        raise ValueError('Adaptive inputs cannot be negative')
    for source in (profile['demographics']['populationSource'], profile['tourism']['source'], profile['geography']['areaSource']):
        if not source:
            raise ValueError('Adaptive inputs must have provenance URLs')
    raw = 80 + 4*math.sqrt(population/1000) + 3*math.sqrt(tourism/1000) + 1.5*math.sqrt(area)
    return int(math.floor(min(1200, max(100, raw))/25 + .5)*25)


def validate(dataset, schema, taxonomy, profile, config):
    errors, warnings = [], []
    def err(msg): errors.append(msg)
    def warn(msg): warnings.append(msg)

    for problem in sorted(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(dataset), key=lambda p: str(p.path)):
        path = '.'.join(map(str, problem.absolute_path)) or '$'
        err(f'SCHEMA {path}: {problem.message}')
    if errors:
        return {'passed': False, 'errors': errors, 'warnings': warnings, 'counts': {}}

    meta = dataset['metadata']
    if meta['destinationId'] != profile['id'] or meta['destinationId'] != config['destinationId']:
        err('Destination identifiers do not match')
    if meta['schemaVersion'] != config['schemaVersion']:
        err('Schema version does not match config')
    if dataset['taxonomy'] != {k: taxonomy[k] for k in ('categories','subcategories','tags')}:
        err('Dataset taxonomy must exactly match supplied taxonomy.json for reproducibility')
    ids = set()
    source_ids = set()
    for source in dataset['sources']:
        if source['id'] in source_ids:
            err(f'Duplicate source ID {source["id"]}')
        source_ids.add(source['id'])
    cats = {c['id'] for c in taxonomy['categories']}
    subcat_parent = {s['id']: s['category'] for s in taxonomy['subcategories']}
    tags = {t['id'] for t in taxonomy['tags']}
    if len(cats) != len(taxonomy['categories']): err('Duplicate taxonomy category IDs')
    if len(subcat_parent) != len(taxonomy['subcategories']): err('Duplicate taxonomy subcategory IDs')
    if len(tags) != len(taxonomy['tags']): err('Duplicate taxonomy tag IDs')
    categories = collections.Counter()
    subcategories = collections.Counter()
    tagcounts = collections.Counter()
    hg_categories = set()
    license_unknown = 0
    rated = 0
    rated_expected = 0
    seen_names = collections.defaultdict(list)
    lines = set()
    hub_count = 0
    b = profile['geography']['boundingBox']
    for idx,poi in enumerate(dataset['pois']):
        prefix = f'pois[{idx}] ({poi["id"]})'
        if poi['id'] in ids: err(f'{prefix}: duplicate ID')
        ids.add(poi['id'])
        if not poi['id'].startswith(profile['id']+':'):
            warn(f'{prefix}: ID not prefixed with destination ID; this may be intentional with global IDs')
        if poi['category'] not in cats: err(f'{prefix}: unknown category {poi["category"]}')
        if subcat_parent.get(poi['subcategory']) != poi['category']:
            err(f'{prefix}: subcategory {poi["subcategory"]} is not in category {poi["category"]}')
        for tag in poi['tags']:
            if tag not in tags: err(f'{prefix}: unknown tag {tag}')
            tagcounts[tag] += 1
        for tag in poi['tagRationales']:
            if tag not in poi['tags']: err(f'{prefix}: rationale tag {tag} absent from tags')
        categories[poi['category']] += 1
        subcategories[poi['subcategory']] += 1
        if meta['destinationId'] not in poi['location']['destinationIds']:
            err(f'{prefix}: destinationIds does not contain active destination')
        lat,lon=poi['location']['latitude'],poi['location']['longitude']
        if not (b['south'] <= lat <= b['north'] and b['west'] <= lon <= b['east']):
            err(f'{prefix}: outside benchmark coarse bounding box; manual boundary review still necessary')
        if poi['location']['address']['country'] != profile['geography']['country']:
            err(f'{prefix}: country mismatch')
        name_key = re.sub(r'\W+', '',poi['name'].casefold())
        seen_names[name_key].append((poi['id'],lat,lon))
        supported = set()
        evidence_source_ids = set()
        for evidence in poi['evidence']:
            if evidence['sourceId'] not in source_ids:
                err(f'{prefix}: evidence references unknown source {evidence["sourceId"]}')
            supported.update(evidence['supports'])
            evidence_source_ids.add(evidence['sourceId'])
        for field in config['quality']['requireEvidence']:
            if field not in supported: err(f'{prefix}: evidence missing {field}')
        if 'hidden_gem' in poi['tags']:
            hg_categories.add(poi['category'])
            if not poi['tagRationales'].get('hidden_gem','').strip():
                err(f'{prefix}: hidden_gem rationale missing')
            if config['quality']['hiddenGemMustHaveEvidence'] and 'hidden_gem_reason' not in supported:
                err(f'{prefix}: hidden gem rationale lacks evidence')
        license = poi['media']['primaryImage']['license']
        if license.strip().lower() == 'unknown': license_unknown += 1
        if license.strip().lower() == 'unknown' and not config['quality']['imageLicenseUnknownAllowed']:
            err(f'{prefix}: unknown image license disallowed')
        if poi['media']['primaryImage']['url'] == poi['media']['primaryImage']['sourcePageUrl']:
            warn(f'{prefix}: image URL same as source page; check direct image asset')
        gmap = urlparse(poi['links']['googleMaps'])
        if gmap.hostname not in ('www.google.com','google.com','maps.google.com','maps.app.goo.gl'):
            err(f'{prefix}: Google Maps URL is not on an accepted Google Maps host')
        if 'maps/place/' not in gmap.path and '/maps?cid=' not in poi['links']['googleMaps'] and 'maps.app.goo.gl' not in gmap.hostname and '/maps/' not in gmap.path:
            warn(f'{prefix}: Google Maps URL may be a generic search rather than direct place')
        score = poi['ratings']['google']
        if poi['category'] == 'gastronomy' and poi['subcategory'] not in config['quality']['googleRatingRequiredExceptSubcategories']:
            rated_expected += 1
            if score is None: err(f'{prefix}: missing Google rating for gastronomic business')
        if score is not None:
            rated += 1
            if poi['category']=='gastronomy' and score['score'] < config['quality']['gastronomyGoogleMinScore']:
                err(f'{prefix}: Google rating {score["score"]} below required {config["quality"]["gastronomyGoogleMinScore"]}')
            if score['reviewCount'] == 0: warn(f'{prefix}: rating has zero reviews; verify')
        if poi['category']=='transport':
            t = poi['transit']
            if t['mode']=='metro': lines.update(t['lines'])
            if t['isInterchange'] or poi['subcategory'] in ('railway_station','transport_interchange','airport_connection'):
                hub_count += 1
        if not poi['links']['reference'] or not poi['media']['primaryImage']['url']:
            err(f'{prefix}: required reference or image missing')
        if 'image' not in supported:
            warn(f'{prefix}: image has URL metadata but no explicit evidence.supports=image')
    for records in seen_names.values():
        if len(records)>1:
            for n in range(len(records)):
                for m in range(n+1,len(records)):
                    a,b0 = records[n],records[m]
                    dlat=(a[1]-b0[1])*111000
                    dlon=(a[2]-b0[2])*111000*math.cos(math.radians(a[1]))
                    if math.hypot(dlat,dlon)<50:
                        warn(f'Potential duplicate name & location: {a[0]} and {b0[0]} (<50m)')
    minimum = compute_target(profile, config)
    if len(dataset['pois']) < minimum:
        err(f'POI count {len(dataset["pois"])} < minimum {minimum}')
    for category, n in config['target']['categoryMinimums'].items():
        if categories[category] < n: err(f'Category {category}: {categories[category]} < {n}')
    for tag, n in config['target']['tagMinimums'].items():
        if tagcounts[tag] < n: err(f'Tag {tag}: {tagcounts[tag]} < {n}')
    for category, n in config['target']['subcategoryCoverageMinimums'].items():
        distinct = sum(1 for s in taxonomy['subcategories'] if s['category']==category and subcategories[s['id']] > 0)
        if distinct < n: err(f'Category {category}: only {distinct} populated subcategories < {n}')
    if len(hg_categories) < config['target']['hiddenGemCategoryMinimum']:
        err(f'Hidden gems appear in only {len(hg_categories)} categories')
    for metro in config['target']['requiredMetroLines']:
        if metro not in lines: err(f'Metro line {metro} not represented')
    if hub_count < config['target']['majorTransportHubsMinimum']:
        err(f'Only {hub_count} transit hub candidates; expected >= {config["target"]["majorTransportHubsMinimum"]}')
    if len(dataset['pois']) > config['target']['maximumSoft']:
        warn('POI count above soft maximum; investigate whether excessive low-value duplicates exist')
    result={'passed':not errors,'errors':errors,'warnings':warnings,'counts':{'total':len(dataset['pois']),'byCategory':dict(categories),'byTag':dict(tagcounts),'bySubcategory':dict(subcategories),'metroLines':sorted(lines),'transitHubCandidates':hub_count},'ratingCoverage':{'requiredBusinessCount':rated_expected,'withGoogleRatingTotal':rated},'imageLicenseUnknownCount':license_unknown}
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dataset',type=pathlib.Path)
    parser.add_argument('--report',type=pathlib.Path,default=None)
    args=parser.parse_args(argv)
    try:
        data=load(args.dataset)
        schema=load(ROOT/'poi.schema.json')
        taxonomy=load(ROOT/'taxonomy.json')
        config=load(ROOT/'benchmark.config.json')
        profile=load(ROOT/'destination.json')
        outcome=validate(data,schema,taxonomy,profile,config)
    except (OSError,ValueError,KeyError,TypeError,json.JSONDecodeError) as exc:
        outcome={'passed':False,'errors':[f'VALIDATOR: {exc}'],'warnings':[],'counts':{}}
    status='pass_automated' if outcome['passed'] else 'fail_automated'
    report={'benchmarkId':'universal-poi-discovery/rome/v1','datasetVersion':data.get('metadata',{}).get('datasetVersion') if 'data' in locals() and isinstance(data,dict) else None,'generatedAt':datetime.datetime.now(datetime.timezone.utc).isoformat(),'status':status,'automated':outcome,'manualReview':{'status':'not_started','sampleSize':None,'findings':[]},'limitations':['Automated validation does NOT verify real-world existence, exact coordinates, functioning URLs, image identity, licensing, Google ratings or source accuracy.']}
    if args.report:
        args.report.parent.mkdir(parents=True,exist_ok=True)
        args.report.write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(json.dumps({'status':status,'errors':outcome['errors'][:50],'warnings':outcome['warnings'][:20],'counts':outcome['counts']},indent=2,ensure_ascii=False))
    return 0 if outcome['passed'] else 1

if __name__=='__main__':
    sys.exit(main())
