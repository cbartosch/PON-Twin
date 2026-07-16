import json
d = json.load(open('pon_data.json', encoding='utf-8'))
sbu = [a for a in d['areas'] if a.get('tier') == 2]
print('SBU parents:')
for a in sorted(sbu, key=lambda x: -x['olt_count']):
    print("  %-28s olts=%4d fdt=%6d fat=%7d homes~=%8d" % (
        a['area_id'], a['olt_count'], a['primary_splitter_count'],
        a['fat_count'], a['connected_homes_operator_B']))
orph = [a['area_id'] for a in d['areas'] if a.get('tier2_parent_code') == 'SBU-UNSPECIFIED']
print('KP still orphaned:', orph)
