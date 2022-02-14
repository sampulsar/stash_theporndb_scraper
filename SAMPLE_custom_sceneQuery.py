import re


# implement your own logic here
# This is primarily useful if you have a group of files that
#   do not conform to the standard naming scheme
#
# For example here's my code to search on the LegalPorno scene ID and date
#
def sceneQuery(query_in: str) -> str:
    scene_id = ''
    scene_date = ''
    if re.search('legal ?porno', query_in.lower()):
        if re.search(r' (\d{4}-\d{2}-\d{2}) ', query_in):
            scene_date = re.search(r' (\d{4}-\d{2}-\d{2}) ', query_in).group(1) + "%20"
        else:
            scene_date = ''

        if re.search(r'([a-zA-Z]{2,3}\d{3,4})', query_in):
            scene_id = re.search(r'([a-zA-Z]{2,3}\d{3,4})', query_in).group(1).strip()

    if scene_id:
        url = f'https://api.metadataapi.net/api/scenes?q={scene_date} {scene_id}'
        return url

    return query_in
