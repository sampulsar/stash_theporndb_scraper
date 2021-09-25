#!/usr/bin/python3

import datetime
import os
import requests
import json
import re
import urllib
import sys
import base64
import math
import logging
import argparse
import traceback
import time
import difflib
import copy
from io import BytesIO
from urllib.parse import quote
from PIL import Image
from requests.packages.urllib3.exceptions import InsecureRequestWarning
from pathlib import Path

import StashInterface

custom_clean_name = None
if Path(__file__).with_name('custom.py').is_file():
    from custom import clean_name as custom_clean_name

###########################################################
#CONFIGURATION OPTIONS HAVE BEEN MOVED TO CONFIGURATION.PY#
###########################################################

#Metadataapi API settings
STOCKAGE_FILE_APIKEY = "Adultime_key.txt"
AdultTime_sleep = 1  # time to sleep before each API req
ADULTIME_HEADERS = {
    "User-Agent": 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:79.0) Gecko/20100101 Firefox/79.0',
    "Origin": "https://members.adulttime.com",
    "Referer": "https://members.adulttime.com/"
}

stash_b64_header = "data:image/jpg;base64," # actual mime doesn't matter

#Utility Functions
def lreplace(pattern, sub, string):
    """
    Replaces 'pattern' in 'string' with 'sub' if 'pattern' starts 'string'.
    """
    return re.sub('^%s' % pattern, sub, string)

def cleanString(string):
    string = string.replace('-', ' ')
    string = string.replace("'", '')
    string = string.replace(":", '')
    string = string.replace("#", ' ')
    string = string.replace(" 480p ", ' ')
    string = string.replace(" mp4 ", ' ')

    return string
    
def stripString(string):
    if string is None or string == "": 
        return ""
        
    string = string.lower()
    string = cleanString(string)
    string = string.replace(',', ' ')
    string = string.replace('?', ' ')
    string = string.replace('.', ' ')
    string = string.replace('!', ' ')
    string = string.replace(" & ", ' ')
    string = string.replace(" and ", ' ')
    string = string.replace(' ', '')
    
    return string
    
def scrubFileName(file_name):
    clean_name = file_name
    # add support for custom name cleaning
    if custom_clean_name is not None:
        clean_name = custom_clean_name(clean_name)
    else:
        scrubbedWords = ['MP4-(.+?)$', ' XXX ', '1080p', '720p', 'WMV-(.+?)$', '-UNKNOWN', ' x264-(.+?)$', 'DVDRip', 'WEBRIP', 'WEB', '\[PRiVATE\]', 'HEVC', 'x265', 'PRT-xpost', '-xpost', '480p', '2160p', ' SD', ' HD', '\'', '&']        
        clean_name = re.sub('\.', ' ', clean_name)  ##replace periods
        for word in scrubbedWords:  ##delete scrubbedWords
            clean_name = re.sub(word, '', clean_name, 0, re.IGNORECASE)

    clean_name = clean_name.strip()  #trim
    return clean_name


def keyIsSet(json_object, fields):  #checks if field exists for json_object.  If "fields" is a list, drills down through a tree defined by the list
    if json_object:
        if isinstance(fields, list):
            for field in fields:
                if field in json_object and json_object[field] != None:
                    json_object = json_object[field]
                else:
                    return False
            return True
        else:
            if fields in json_object and json_object[fields] != None:
                return True
    return False

#Script-specific functions
def createStashPerformerData(AdultTime_performer):  #Creates stash-compliant data from raw data provided by traxxx
    stash_performer = {}
    if keyIsSet(AdultTime_performer, ["name"]):
        stash_performer["name"] = AdultTime_performer["name"]
    if keyIsSet(AdultTime_performer, ["description"]):
        stash_performer["details"] = AdultTime_performer["description"]
        
    #if keyIsSet(AdultTime_performer, ["dateOfBirth"]):
    #    stash_performer["birthdate"] = AdultTime_performer["dateOfBirth"]
        
    #if keyIsSet(AdultTime_performer, ["placeOfResidence", "country", "name"]):
    #    stash_performer["country"] = AdultTime_performer["placeOfResidence"]["country"]["name"]
    #if keyIsSet(AdultTime_performer, ["height"]):
    #    stash_performer["height"] = str(AdultTime_performer["height"])
    if keyIsSet(AdultTime_performer, ["attributes", "ethnicity"]):
        stash_performer["ethnicity"] = AdultTime_performer["attributes"]["ethnicity"]
    if keyIsSet(AdultTime_performer, ["attributes", "eye_color"]):
        stash_performer["eye_color"] = AdultTime_performer["attributes"]["eye_color"]
    if keyIsSet(AdultTime_performer, ["attributes", "hair_color"]):
        stash_performer["hair_color"] = AdultTime_performer["attributes"]["hair_color"]
    #if keyIsSet(AdultTime_performer, ["tattoos"]):
    #    stash_performer["tattoos"] = AdultTime_performer["tattoos"]
    #if keyIsSet(AdultTime_performer, ["piercings"]):
    #    stash_performer["piercings"] = AdultTime_performer["piercings"]
    if keyIsSet(AdultTime_performer, ["pictures", "500x750"]):
        stash_performer["image"] = "https://transform.gammacdn.com/actors" + AdultTime_performer["pictures"]["500x750"]
    if keyIsSet(AdultTime_performer, ["gender"]):
        if AdultTime_performer["gender"] == "male":
            stash_performer["gender"] = 'MALE'
        if AdultTime_performer["gender"] == "female":
            stash_performer["gender"] = 'FEMALE'
        if AdultTime_performer["gender"] == "transgender male":
            stash_performer["gender"] = 'TRANSGENDER_MALE'
        if AdultTime_performer["gender"] == "transgender female":
            stash_performer["gender"] = 'TRANSGENDER_FEMALE'
        if AdultTime_performer["gender"] == "intersex":
            stash_performer["gender"] = 'INTERSEX'
            
    return stash_performer

def createStashStudioData(AdultTime_studio):  # Creates stash-compliant data from raw data provided by traxxx
    stash_studio = {}
    
    parent_scraped_studio = None
    if keyIsSet(AdultTime_studio, ['parentChannel']) and AdultTime_studio["parentChannel"] is not None:
        parent_scraped_studio = getChannel(AdultTime_studio["parentChannel"])
        
    if parent_scraped_studio is not None:
        if keyIsSet(parent_scraped_studio, ['channelType']) and parent_scraped_studio['channelType'] == "network" and config.studio_network_suffix:
            parent_scraped_studio["name"] = parent_scraped_studio["name"] + config.studio_network_suffix

        parent_stash_studio = my_stash.getStudioByName(parent_scraped_studio['name'])
        if parent_stash_studio is not None:
            stash_studio["parent_id"] = parent_stash_studio["id"]
        else:
            stash_studio["parent_id"] = my_stash.addStudio((createStashStudioData(parent_scraped_studio)))
    
    if config.compact_studio_names:
        stash_studio["name"] = AdultTime_studio["name"].replace(' ', '')
    else:
        stash_studio["name"] = AdultTime_studio["name"]
    
    if keyIsSet(AdultTime_studio, ['tagline']):
        stash_studio["details"] = AdultTime_studio["tagline"]   
    
    if keyIsSet(AdultTime_studio, ["avatar", "src"]):
        stash_studio["image"] = "http:" + AdultTime_studio["avatar"]["src"]
    #short_name into aliases
    
    return stash_studio
            
def getJpegImage(image_url):
    try:

        r = requests.get(image_url, stream=True, proxies=config.proxies)
        r.raw.decode_content = True  # handle spurious Content-Encoding
        image = Image.open(r.raw)
        if image.format:
            if image.mode in ('RGBA', 'LA'):
                fill_color = 'black'  # your background
                background = Image.new(image.mode[:-1], image.size, fill_color)
                background.paste(image, image.split()[-1])
                image = background
            buffered = BytesIO()
            image.save(buffered, format="JPEG")
            image = buffered.getvalue()
            return image

    except Exception as e:
        logging.error("Error Getting Image at URL:" + image_url, exc_info=config.debug_mode)

    return None

def getChannel(channelName):
    global api_url
    channel_data = api_search_req("channel_id", channelName, api_url)
    if (channel_data is not None and len(channel_data) == 1):
        return channel_data[0]
        
    return None

def getPerformer(performer):
    global api_url
    performer_data = api_search_req("actor_id", performer['actor_id'], api_url)
    if (len(performer_data) == 1):
        performer = performer_data[0]
        # print(performer["attributes"])
        if " " not in performer["name"]:
            performer["name"] = performer["name"] + " (AdultTime [" + str(performer['actor_id']) + "])"
    
    return performer

def getBabepediaImage(name):
    url = "https://www.babepedia.com/pics/" + urllib.parse.quote(name) + ".jpg"
    r = requests.get(url, proxies=config.proxies)
    if r.status_code >= 400:
        return None
    else:
        return getJpegImage(url)
    return None


def getPerformerImageB64(name):  #Searches Babepedia and TPBD for a performer image, returns it as a base64 encoding
    global my_stash
    global config
    try:
        performer = my_stash.getPerformerByName(name)

        #Try Babepedia if flag is set
        if config.get_images_babepedia:
            # Try Babepedia
            image = getBabepediaImage(name)
            if image:
                image_b64 = base64.b64encode(image)
                stringbase = str(image_b64)
                return stash_b64_header + image_b64.decode(ENCODING)

            # Try aliases at Babepedia
            if performer and performer.get("aliases", None):
                for alias in performer["aliases"]:
                    image = getBabepediaImage(alias)
                    if image:
                        image_b64 = base64.b64encode(image)
                        stringbase = str(image_b64)
                        return stash_b64_header + image_b64.decode(ENCODING)

        return None
    except Exception as e:
        logging.error("Error Getting Performer Image", exc_info=config.debug_mode)

def sceneQuery(query):  # Scrapes Traxxx based on query.  Returns an array of scenes as results, or None
    global AdultTime_headers
    global AdultTime_error_count
    url = config.AdultTime_server_URL + "/api/scenes?limit=3&q=" + urllib.parse.quote(query.replace(" ", "."))
    result = None
    try:
        time.sleep(AdultTime_sleep)  # sleep before every request to avoid being blocked
        result = requests.get(url, proxies=config.proxies, timeout=(3, 15), headers=AdultTime_headers)
        AdultTime_error_count = 0
        if result.status_code >= 400:
            logging.error('Traxxx HTTP Error: %s' % result.status_code)
            return None
        return result.json()["scenes"]
    except ValueError:
        logging.error("Error communicating with Traxxx")
        AdultTime_error_count = AdultTime_error_count + 1
        if AdultTime_error_count > 3:
            logging.error("Traxxx seems to be down.  Exiting.")
            sys.exit()
    except Exception:
        logging.error("Error communicating with Traxxx", exc_info=config.debug_mode)
        if result is None:
            print(url)
            print("No Result")
        else:
            print(result)

    return None

def autoDisambiguateResults(scene, scrape_query, performers, clip_path, scraped_data):
    new_data = []
    matched_scene = None
    matched_item_name = ""
    
    for scraped_scene in scraped_data:
        match_clip = False
        match_ratio = 0
        
        first_item = scraping_json(scraped_scene, None)
        first_item_name = ""
        first_clip_path = ""
        
        #clip_path
        if keyIsSet(scraped_scene, ['clip_path']): 
            first_clip_path = scraped_scene['clip_path'].split('_')[1]
            if (str(clip_path) == str(first_clip_path)):
                match_clip = True
        else:
            match_clip = True
        
        performer_names = []
        if first_item['performers']:
            for scraped_performer in first_item["performers"]:
                not_female = False
                 
                if keyIsSet(scraped_performer, ["gender"]) and scraped_performer["gender"] != 'female':
                    not_female = True

                if (not_female):
                    continue  # End current loop on male performers not in path

                performer_names.append(scraped_performer['name'])

            #first_item_name =  first_item_name + " " + ' '.join(map(str, performer_names))

        
        if scene['title'] and first_item['title']:
            title = first_item['title']
            scene_title = scene['title']
            
            temp_ratio = difflib.SequenceMatcher(None, 
                stripString(title), 
                stripString(scene_title)).ratio()
            if match_ratio <= temp_ratio:
                match_ratio = temp_ratio
            
            temp_ratio = difflib.SequenceMatcher(None, 
                stripString(' '.join(map(str, performer_names)) + title), 
                stripString(scene_title)).ratio()
            if match_ratio <= temp_ratio:
                match_ratio = temp_ratio
            
            temp_ratio = difflib.SequenceMatcher(None, 
                stripString(' '.join(map(str, performer_names))), 
                stripString(scene_title)).ratio()
            if match_ratio <= temp_ratio:
                match_ratio = temp_ratio
            
            first_item_name =  first_item_name + " " + title
                
            temp_ratio = difflib.SequenceMatcher(None, 
                stripString(first_item_name), 
                stripString(scrape_query)).ratio()
            
            if match_ratio <= temp_ratio:
                match_ratio = temp_ratio


            first_item_name =  first_item_name + " (" + str(match_ratio) + ")"

        first_item_name =  first_item_name + " " + ' '.join(map(str, performer_names))
        first_item_name =  first_item_name + " [" + first_clip_path + "]"
        
        if match_clip == True and match_ratio == 1:
            matched_scene = scraped_scene
            new_data.append(matched_scene)
            matched_item_name = first_item_name
        
    if matched_scene is None:
        return scraped_data

    print("Found Data For:    " + matched_item_name )
    
    return new_data


def manuallyDisambiguateResults(scraped_data):
    print("Found ambiguous result.  Which should we select?:")
    for index, json in enumerate(scraped_data):
        scene = scraping_json(json, None)
        print(index + 1, end=': ')
        if keyIsSet(scene, ['studio', 'name']):
            print(scene['studio']['name'], end=" ")
        if keyIsSet(scene, ['date']) and scene['date']: print(scene['date'], end=" ")
        if keyIsSet(scene, ['title']): print(scene['title'], end=" ")
        if keyIsSet(json, ['clip_path']): print('[' + json['clip_path'].split('_')[1] + ']', end=" ")
        
        if keyIsSet(scene, ['performers']):
            performer_names = []
            for scraped_performer in scene["performers"]:
                not_female = False
                 
                if keyIsSet(scraped_performer, ["gender"]) and scraped_performer["gender"] != 'female':
                    not_female = True

                if (not_female):
                    continue  # End current loop on male performers not in path

                performer_names.append(scraped_performer['name'])
            print('(' + ", ".join(performer_names) + ')', end=" ")
        
        print('')
    print("0: None of the above.  Skip this scene.")

    selection = -1
    while selection < 0 or selection > len(scraped_data):
        try:
            selection = int(input("Selection: "))
            if selection < 0 or selection > len(scraped_data):
                raise ValueError
        except ValueError:
            print("Invalid Selection")

    if selection == 0:
        return []
    else:
        new_data = []
        new_data.append(scraped_data[selection - 1])
        return new_data

def getQuery(scene):
    global config
    try:
        if re.search(r'^[A-z]:\\', scene['path']):  #If we have Windows-like paths
            parse_result = re.search(r'^[A-z]:\\((.+)\\)*(.+)\.(.+)$', scene['path'])
            dirs = parse_result.group(2).split("\\")
        else:  #Else assume Unix-like paths
            parse_result = re.search(r'^\/((.+)\/)*(.+)\.(.+)$', scene['path'])
            dirs = parse_result.group(2).split("/")
        file_name = parse_result.group(3)
    except Exception:
        logging.error("Error when parsing scene path: " + scene['path'], exc_info=config.debug_mode)

    if config.parse_with_filename:
        if file_name is None:
            return
        if config.clean_filename:
            file_name = scrubFileName(file_name)

        scrape_query = file_name
        #ADD DIRS TO QUERY
        for x in range(min(config.dirs_in_query, len(dirs))):
            scrape_query = dirs.pop() + " " + scrape_query
    else:
        scrape_query = ''
        # scene = scrubScene(scene, dirs, file_name)

        if keyIsSet(scene, ["studio", "name"]):
            scrape_query = scrape_query + ' ' + (scene['studio']['name'])

        if scene['date']:
            scrape_query = scrape_query + ' ' + scene['date']
            
        scrape_query = scrape_query + ' ' +  (scene['title'])

    return '' if scrape_query is None else str(scrape_query.strip())

def scrapeScene(scene):
    global my_stash
    global config
    global api_url
    try:
        scene_data = my_stash.createSceneUpdateData(scene)  # Start with our current data as a template
        SCENE_ID = scene_data["id"]
        SCENE_TITLE = scene_data["title"]
        SCENE_PERFORMERS = scene_data["title"]
        pathSplit = scene.get("path").split('/')
        SCENE_STUDIO = pathSplit[len(pathSplit) - 2]
        CLIP_PATH = None
        SCENE_URL = None
        if keyIsSet(scene, ['url']): SCENE_URL = scene_data["url"]
        
        if SCENE_URL and SCENE_ID is None:
            logging.debug("[DEBUG] URL Scraping: {}".format(SCENE_URL))
        else:
            logging.debug("[DEBUG] Stash ID: {}".format(SCENE_ID))
            logging.debug("[DEBUG] Stash Title: {}".format(SCENE_TITLE))
        
        # Extract things
        url_title = None
        url_id = None
        url_domain = None
        if SCENE_URL:
            url_domain = re.sub(r"www\.|\.com","",urlparse(SCENE_URL).netloc)
            logging.debug("[INFO] URL Domain: {}".format(url_domain))
            url_id_check = re.sub('.+/', '', SCENE_URL)
            # Gettings ID
            try:
                if url_id_check.isdigit():
                    url_id = url_id_check
                else:
                    url_id = re.search(r"/(\d+)/*", SCENE_URL).group(1)
                logging.debug("[INFO] ID: {}".format(url_id))
            except:
                logging.debug("[WARN] Can't get ID from URL")
            # Gettings url_title
            try:
                url_title = re.match(r".+/(.+)/\d+", SCENE_URL).group(1)
                logging.debug("[INFO] URL_TITLE: {}".format(url_title))
            except:
                logging.debug("[WARN] Can't get url_title from URL")
        
        # Filter title
        if SCENE_TITLE:
            title = SCENE_TITLE
            clip_path_search = re.search('_s(\d{2})_', title, re.IGNORECASE)
            if clip_path_search:
                CLIP_PATH = clip_path_search.group(1)
                if (title.find("_s0") != -1):
                    SCENE_TITLE = title[0:title.find("_s0")]
                if (title.find("_s1") != -1):
                    SCENE_TITLE = title[0:title.find("_s1")]
                SCENE_PERFORMERS = SCENE_PERFORMERS.replace(SCENE_TITLE, '')

            SCENE_TITLE = SCENE_TITLE.replace("POV", " POV ") 
            SCENE_TITLE = re.sub("([a-z])([A-Z])", "\g<1> \g<2>", SCENE_TITLE)
            SCENE_TITLE = re.sub("([A-Z])([A-Z])([a-z])", "\g<1> \g<2>\g<3>", SCENE_TITLE)
            SCENE_TITLE = re.sub(r'[-._\']', ' ', os.path.splitext(SCENE_TITLE)[0])
            # Remove resolution
            SCENE_TITLE = re.sub(r'\sXXX|\s1080p|720p|480p|2160p|KTR|RARBG|\scom\s|\[|]|\sHD|\sSD|', '', SCENE_TITLE)
            SCENE_PERFORMERS = re.sub(r'\sXXX|\s1080p|720p|480p|2160p|KTR|RARBG|\scom\s|\[|]|\sHD|\sSD|', '', SCENE_PERFORMERS)
            # Remove Date
            SCENE_TITLE = re.sub(r'\s\d{2}\s\d{2}\s\d{2}|\s\d{4}\s\d{2}\s\d{2}', '', SCENE_TITLE)
            SCENE_PERFORMERS = re.sub(r'_s(\d{2})_', '', SCENE_PERFORMERS)
            SCENE_PERFORMERS = SCENE_PERFORMERS.replace('_', ' ')
            SCENE_PERFORMERS = re.sub("([a-z])([A-Z])", "\g<1> \g<2>", SCENE_PERFORMERS)
    
            logging.debug("[INFO] Title: {}".format(SCENE_TITLE))
            logging.debug("[INFO] Performers: {}".format(SCENE_PERFORMERS))
            logging.debug("[INFO] Clip Path: {}".format(CLIP_PATH))

        scraped_data = None
        
        if url_id:
            logging.debug("[API] Searching using URL_ID")
            scraped_data = api_search_req("id", url_id, api_url)
            if scraped_data:
                logging.debug("[API] Search give {} result(s)".format(len(scraped_data)))
            else:
                logging.debug("[API] No result")
        if url_title and scraped_data is None:
            logging.debug("[API] Searching using URL_TITLE")
            scraped_data = api_search_req("query", url_title, api_url)
            if scraped_data:
                logging.debug("[API] Search give {} result(s)".format(len(scraped_data)))
        if SCENE_TITLE and scraped_data is None:
            logging.debug("[API] Searching using STASH_TITLE")
            scraped_data = api_search_req("query", SCENE_STUDIO + ' ' + SCENE_TITLE + ' ' + SCENE_PERFORMERS, api_url)
            if scraped_data:
                logging.debug("[API] Search give {} result(s)".format(len(scraped_data)))

        scrape_query = ""
        print("Grabbing Data For: ", end=" ")
        if SCENE_STUDIO is not None: 
            scrape_query = scrape_query + SCENE_STUDIO + " "
            print(SCENE_STUDIO, end=" ")
        if SCENE_TITLE is not None: 
            scrape_query = scrape_query + SCENE_TITLE + " "
            print(SCENE_TITLE, end=" ")
        if SCENE_PERFORMERS is not None: 
            print(SCENE_PERFORMERS, end=" ")
        if CLIP_PATH is not None: 
            scrape_query = scrape_query + '[' + CLIP_PATH + ']'
            print('[' + CLIP_PATH + ']', end=" ")
        print()
        
        if scraped_data is None:
            #get api again
            if os.path.exists(STOCKAGE_FILE_APIKEY):
                os.remove(STOCKAGE_FILE_APIKEY)
            api_url = get_api()
            return
        
        if len(scraped_data) > 0:  #Auto disambiguate
            scraped_data = autoDisambiguateResults(scene, SCENE_TITLE, SCENE_PERFORMERS, CLIP_PATH, scraped_data)
            #print("Auto disambiguated")
        
        #if len(scraped_data) > 1:  # Manual disambiguate
        #    scraped_data = manuallyDisambiguateResults(scraped_data)
            
        if len(scraped_data) > 1 and config.manual_disambiguate:  # Manual disambiguate
            scraped_data = manuallyDisambiguateResults(scraped_data)
            
        if len(scraped_data) > 1:  # Handling of ambiguous scenes
            print("Ambiguous data found for: [{}], skipping".format(scrape_query))
            if config.ambiguous_tag:
                scene_data["tag_ids"].append(my_stash.getTagByName(config.ambiguous_tag)['id'])
            my_stash.updateSceneData(scene_data)
            return

        if scraped_data:
            scraped_scene = scraped_data[0]
            # If we got new data, update our current data with the new
            updateSceneFromScrape(scene_data, scraping_json(scraped_scene, None), scene['path'])
            print("Success")
        else:
            scene_data["tag_ids"].append(my_stash.getTagByName(config.unmatched_tag)['id'])
            my_stash.updateSceneData(scene_data)
            print("No data found for: [{}]".format(scrape_query))
    except Exception as e:
        logging.error("Exception encountered when scraping", exc_info=config.debug_mode)


def addPerformer(scraped_performer):  #Adds performer using TPDB data, returns ID of performer
    global config
    stash_performer_data = createStashPerformerData(scraped_performer)
    if config.scrape_performers_freeones:
        freeones_data = my_stash.scrapePerformerFreeones(scraped_performer['name'])
        if freeones_data:
            if keyIsSet(freeones_data, "aliases") and keyIsSet(scraped_performer, ["aliases"]):
                freeones_data['aliases'] = list(set(freeones_data['aliases'] + scraped_performer['aliases']))
            stash_performer_data.update(freeones_data)
    image = getPerformerImageB64(scraped_performer['name'])
    if (image is not None):
        stash_performer_data["image"] = image
    
    return my_stash.addPerformer(stash_performer_data)


def updateSceneFromScrape(scene_data, scraped_scene, path=""):
    global config
    tag_ids_to_add = []
    tags_to_add = []
    performer_names = []
    try:
        if config.ambiguous_tag:
            ambiguous_tag_id = my_stash.getTagByName(config.ambiguous_tag)['id']
            if ambiguous_tag_id in scene_data["tag_ids"]:
                scene_data["tag_ids"].remove(ambiguous_tag_id)  #Remove ambiguous tag; it will be readded later if the scene is still ambiguous
        if config.unmatched_tag:
            unmatched_tag_id = my_stash.getTagByName(config.unmatched_tag)['id']
            if unmatched_tag_id in scene_data["tag_ids"]:
                scene_data["tag_ids"].remove(unmatched_tag_id)  #Remove unmatched tag
        if my_stash.getTagByName(config.unconfirmed_alias)["id"] in scene_data["tag_ids"]:
            scene_data["tag_ids"].remove(my_stash.getTagByName(config.unconfirmed_alias)["id"])  #Remove unconfirmed alias tag; it will be readded later if needed

        if config.set_details:
            scene_data["details"] = scraped_scene["details"]  #Add details
        if config.set_date and keyIsSet(scraped_scene, "date"):
            scene_data["date"] = scraped_scene["date"] #Add date
        if config.set_url and keyIsSet(scraped_scene, "url"): scene_data["url"] = scraped_scene["url"]  #Add URL
        if config.set_cover_image and keyIsSet(scraped_scene, ["poster", "path"]):  #Add cover_image
            cover_image = getJpegImage(config.AdultTime_server_URL + "/media/" + scraped_scene["poster"]['path'])
            if cover_image:
                image_b64 = base64.b64encode(cover_image)
                stringbase = str(image_b64)
                scene_data["cover_image"] = stash_b64_header + image_b64.decode(ENCODING)

        # Add Studio to the scene
        if config.set_studio and keyIsSet(scraped_scene, "studio"):
            studio_id = None
            temp_studio = getChannel(scraped_scene['studio']['sitename'])
            if temp_studio is not None:
                scraped_studio = temp_studio
            if config.compact_studio_names:
                scraped_studio['name'] = scraped_studio['name'].replace(' ', '')
            stash_studio = my_stash.getStudioByName(scraped_studio['name'])
            if stash_studio:
                studio_id = stash_studio["id"]
            elif config.add_studio:
                # Add the Studio to Stash
                print("Did not find " + scraped_studio['name'] + " in Stash.  Adding Studio.")
                studio_id = my_stash.addStudio((createStashStudioData(scraped_studio)))
            if studio_id != None:  # If we have a valid ID, add studio to Scene
                scene_data["studio_id"] = studio_id

        # Add Tags to the scene
        if config.scrape_tag: tags_to_add.append({'tag': config.scrape_tag})
        if config.set_tags and keyIsSet(scraped_scene, "tags"):
            for tag in scraped_scene["tags"]:
                tags_to_add.append({'tag': tag['name']})

        # Add performers to scene
        if config.set_performers and keyIsSet(scraped_scene, "performers"):
            scraped_performer_ids = []
            for scraped_performer in scraped_scene["performers"]:
                not_female = False

                if keyIsSet(scraped_performer, ["gender"]) and scraped_performer["gender"] == 'male':
                    not_female = True

                if (config.only_add_female_performers and not_female):
                    continue  # End current loop on male performers not in path

                performer_id = None
                scraped_performer = getPerformer(scraped_performer)
                performer_name = scraped_performer['name']
                search_name = performer_name                 
                stash_performer = my_stash.getPerformerByName(performer_name)
                add_this_performer = False
                if stash_performer:
                    performer_id = stash_performer["id"]  #If performer already exists, use that
                    if config.male_performers_in_title or not not_female:
                        performer_names.append(performer_name)  #Add to list of performers in scene
                else:  #If site name does not match someone in Stash and TPBD has a linked parent
                    # Add performer if we meet relevant requirements
                    if config.add_performers:
                        print("Did not find " + performer_name + " in Stash.  Adding performer.")
                        performer_id = addPerformer(scraped_performer)
                        if config.male_performers_in_title or not not_female:
                            performer_names.append(performer_name)

                if performer_id:  # If we have a valid ID, add performer to Scene
                    scraped_performer_ids.append(performer_id)

            scene_data["performer_ids"] = list(
                set(scene_data["performer_ids"] + scraped_performer_ids))

        # Set Title
        if config.set_title:
            title_prefix = ""
            if config.include_performers_in_title:
                if len(performer_names) > 2:
                    title_prefix = "{}, and {} ".format(
                        ", ".join(performer_names[:-1]), performer_names[-1])
                elif len(performer_names) == 2:
                    title_prefix = performer_names[
                        0] + " and " + performer_names[1] + " "
                elif len(performer_names) == 1:
                    title_prefix = performer_names[0] + " "
                for name in performer_names:
                    scraped_scene["title"] = lreplace(name, '', scraped_scene["title"]).strip()
            scene_data["title"] = str(title_prefix + scraped_scene["title"]).strip()

        # Set tag_ids for tags_to_add
        for tag_dict in tags_to_add:
            tag_id = None
            tag_name = tag_dict['tag'].replace('-', ' ').replace('(', '').replace(')', '').strip().title()
            if config.add_tags:
                tag_id = my_stash.getTagByName(tag_name, add_tag_if_missing=True)["id"]
            else:
                stash_tag = my_stash.getTagByName(tag_name, add_tag_if_missing=False)
                if stash_tag:
                    tag_id = stash_tag["id"]
                else:
                    tag_id = None
            if tag_id:  # If we have a valid ID, add tag to Scene
                tag_ids_to_add.append(tag_id)
            else:
                logging.debug("Tried to add tag \'" + tag_dict['tag'] + "\' but failed to find ID in Stash.")
        scene_data["tag_ids"] = list(set(scene_data["tag_ids"] + tag_ids_to_add))

        logging.debug("Now updating scene with the following data:")
        logging.debug(scene_data)
        my_stash.updateSceneData(scene_data)
    except Exception as e:
        logging.error("Scrape succeeded, but update failed:", exc_info=config.debug_mode)

# General

def sendRequest(url, head, json=""):
    response = requests.post(url, headers=head,json=json, timeout=10)
    if response.content and response.status_code == 200:
        return response
    else:
        logging.debug("[REQUEST] Error, Status Code: {}".format(response.status_code))
    return None

# API Authentification
def apikey_check(time):
    if (os.path.isfile(STOCKAGE_FILE_APIKEY) == True):
        with open(STOCKAGE_FILE_APIKEY) as f:
            list_f = f.read().split("|")
        time_past = datetime.datetime.strptime(list_f[0], '%Y-%m-%d %H:%M:%S.%f')
        if time_past.hour-1 < time.hour < time_past.hour+1 and (time - time_past).days == 0:
            logging.debug("[DEBUG] Using old api keys")
            application_id = list_f[1]
            api_key = list_f[2]
            return application_id, api_key
        else:
            logging.debug("[INFO] Need new api key: [{}|{}|{}]".format(time.hour,time_past.hour,(time - time_past).days))
    return None, None


def apikey_get(site_url,time):
    r = sendRequest(site_url, ADULTIME_HEADERS)
    if r is None:
        return None, None
    script_html = fetch_page_json(r.text)
    if script_html is not None:
        application_id = script_html['api']['algolia']['applicationID']
        api_key = script_html['api']['algolia']['apiKey']
        # Write key into a file
        print("{}|{}|{}".format(time, application_id,api_key), file=open(STOCKAGE_FILE_APIKEY, "w"))
        logging.debug("[INFO] New API keys: {}".format(api_key))
        return application_id, api_key
    else:
        logging.debug("[Error] Can't retrieve API keys from the html ({})".format(site_url))
        return None, None


def fetch_page_json(page_html):
    matches = re.findall(r'window.env\s+=\s(.+);', page_html, re.MULTILINE)
    return None if len(matches) == 0 else json.loads(matches[0])

# API Search Data

def api_search_req(type_search,query,api_url):
    api_request = None
    if type_search == "query":
        api_request = api_search_query(query,api_url)
    if type_search == "id":
        api_request = api_search_id(query,api_url)
    if type_search == "actor_id":
        api_request = api_search_actor_id(query,api_url)
    if type_search == "channel_id":
        api_request = api_search_channel_id(query,api_url)
    if api_request:
        api_search = api_request.json()["results"][0].get("hits")
        if api_search:
            return api_search
    return None


def api_search_id(url_id,api_url):
    clip_id = ["clip_id:{}".format(url_id)]
    request_api = {
        "requests": [
            {
                "indexName": "all_scenes_latest_desc",
                "params": "query=&hitsPerPage=20&page=0",
                "facetFilters": clip_id
            }
        ]
    }
    r = sendRequest(api_url, ADULTIME_HEADERS, request_api)
    return r


def api_search_query(query, api_url):
    request_api = {
        "requests": [
            {
                "indexName": "all_scenes_latest_desc",
                "params": "query=" + query + "&hitsPerPage=20&page=0"
            }
        ]
    }
    r = sendRequest(api_url, ADULTIME_HEADERS, request_api)
    return r

def api_search_actor_id(id,api_url):
    actor_id = ["actor_id:{}".format(id)]
    request_api = {
        "requests": [
            {
                "indexName": "all_actors",
                "params": "query=&hitsPerPage=20&page=0",
                "facetFilters": actor_id
            }
        ]
    }
    r = sendRequest(api_url, ADULTIME_HEADERS, request_api)
    return r

def api_search_channel_id(id,api_url):
    channel_id = ["slug:{}".format(id)]
    request_api = {
        "requests": [
            {
                "indexName": "all_channels",
                "params": "query=&hitsPerPage=20&page=0",
                "facetFilters": channel_id
            }
        ]
    }
    r = sendRequest(api_url, ADULTIME_HEADERS, request_api)
    return r

def get_api():
    CURRENT_TIME = datetime.datetime.now()
    application_id, api_key = apikey_check(CURRENT_TIME)
    # Getting new key
    if application_id is None:
        application_id, api_key = apikey_get("https://www.girlsway.com/en", CURRENT_TIME)
    # Fail getting new key
    if application_id is None:
        sys.exit(1)

    return "https://tsmkfa364q-dsn.algolia.net/1/indexes/*/queries?x-algolia-application-id={}&x-algolia-api-key={}".format(application_id, api_key)

def match_site(argument):
    match = {
        '21sextury':'21Sextury',
        'addicted2girls':'Addicted2Girls',
        'adulttime':'AdultTime',
        'agentredgirl':'Agent Red Girl',
        'alettaoceanempire':'Aletta Ocean Empire',
        'allgirlmassage':'All Girl Massage',
        'analqueenalysa':'Anal Queen Alysa',
        'analteenangels':'Anal Teen Angels',
        'assholefever':'Asshole Fever',
        'austinwilde':'Austin Wilde',
        'biphoria':'BiPhoria',
        'bethecuck':'Be The Cuck',
        'blueangellive':'Blue Angel Live',
        'burningangel':'Burning Angel',
        'buttplays':'Buttplays',
        'cheatingwhorewives':'Cheating Whore Wives',
        'clubinfernodungeon':'Club Inferno Dungeon',
        'clubsandy':'Club Sandy',
        'codycummings':'Cody Cummings',
        'cutiesgalore':'Cuties Galore',
        'deepthroatfrenzy':'Deepthroat Frenzy',
        'devilsfilm':'Devils Film',
        'devilstgirls':'Devils T-Girls',
        # 'dpfanatics':'DPFanatics', Pulled from Gamma
        'evilangel':'Evil Angel',
        'femalesubmission':'Female Submission',
        'footsiebabes':'Footsie Babes',
        'gapeland':'Gapeland',
        'genderx':'Gender X',
        'girlcore':'Girlcore',
        'girlsunderarrest':'Girls Under Arrest',
        'girlstryanal':'Girls Try Anal',
        'girlsway':'Girlsway',
        'hotmilfclub':'Hot MILF Club',
        'isthisreal':'Is This Real',
        'lesbianfactor':'Lesbian Factor',
        'letsplaylez':'Lets Play Lez',
        'lezcuties':'Lez Cuties',
        'marcusmojo':'Marcus Mojo',
        'masonwyler':'Mason Wyler',
        'modeltime':'Model Time',
        'mommysgirl':'Mommys Girl',
        'momsonmoms':'Moms on Moms',
        'nextdoorbuddies':'Nextdoor Buddies',
        'nextdoorcasting':'Nextdoor Casting',
        'nextdoorhomemade':'Nextdoor Homemade',
        'nextdoorhookups':'Nextdoor Hookups',
        'nextdoormale':'Nextdoor Male',
        'nextdoororiginals':'Nextdoor Originals',
        'nextdoorraw':'Nextdoor Raw',
        'nextdoorstudios':'Nextdoor Studios',
        'nextdoortwink':'Nextdoor Twink',
        # 'nudefightclub':'Nude Fight Club', Pulled from Gamma
        'oldyounglesbianlove':'Old Young Lesbian Love',
        'oralexperiment':'Oral Experiment',
        'pixandvideo':'Pix And Video',
        'puretaboo':'Pure Taboo',
        'roddaily':'Rod Daily',
        'samuelotoole':'Samuel Otoole',
        'sistertrick':'Sister Trick',
        'sextapelesbians':'Sextape Lesbians',
        'sexwithkathianobili':'Sex With Kathia Nobili',
        'stagcollectivesolos':'Stag Collective Solos',
        'strokethatdick':'Stroke That Dick',
        'sweetsophiemoone':'Sweet Sophie Moon',
        'tabooheat':'Taboo Heat',
        'tommydxxx':'Tommy D XXX',
        'transfixed':'Transfixed',
        'trickyspa':'Tricky Spa',
        'TransgressiveFilms':'Transgressive Films',
        'truelesbian.com':'True Lesbian',
        'trystanbull':'Trystan Bull',   
        'webyoung':'Web Young',
        'welikegirls':'We Like Girls',
        'wheretheboysarent':'Where the Boys Arent',
        'wicked':'Wicked',
        'zerotolerance':'Zero Tolerance',     
    }
    return match.get(argument, argument)


def scraping_json(api_json, url):
    scrape = {}
    # Title
    if api_json.get('title'):
        scrape['title'] = api_json['title'].strip()
    # Date
    scrape['date'] = api_json.get('release_date')
    # Details
    scrape['details'] = re.sub(r'</br>|<br\s/>|<br>|<br/>', '\n', api_json.get('description'))

    # Studio
    scrape['studio'] = {}
    
    if api_json.get('serie_name'):
        scrape['studio']['name'] = api_json.get('serie_name')
    if api_json.get('sitename'):
        scrape['studio']['sitename'] = api_json.get('sitename')
    if api_json.get('sitename_pretty'):
        scrape['studio']['name'] = api_json.get('sitename_pretty')
    if api_json.get('network_name'):
        scrape['studio']['name'] = api_json.get('network_name')
    if api_json.get('mainChannelName'):
        scrape['studio']['name'] = api_json.get('mainChannelName')
    # Performer
    perf = []
    for x in api_json.get('actors'):
        if x.get('gender') == "female":
            perf.append(x)
    scrape['performers'] = perf

    # Image
    try:
        scrape['image'] = 'https://images03-fame.gammacdn.com/movies' + next(iter(api_json['pictures']['nsfw']['top'].values()))
    except:
        try:
            scrape['image'] = 'https://images03-fame.gammacdn.com/movies' + next(iter(api_json['pictures']['sfw']['top'].values()))
        except:
            debug("[ERROR] Can't manage to get the image for some reason.")
    # URL
    if url:
        scrape['url'] = url
    else:
        if api_json.get('member_url') is not None:
            scrape['url'] = api_json.get('member_url')
        else:
            try:
                scrape['url'] = 'https://members.adulttime.com/en/video/{}/{}/{}'.format(api_json['sitename'], api_json['url_title'], api_json['clip_id'])
            except:
                pass
    return scrape

class config_class:
    ###############################################
    # DEFAULT CONFIGURATION OPTIONS.  DO NOT EDIT #
    ###############################################
    use_https = False  # Set to false for HTTP
    server_ip = "<IP ADDRESS>"
    server_port = "<PORT>"
    username = ""
    password = ""
    ignore_ssl_warnings = True  # Set to True if your Stash uses SSL w/ a self-signed cert
    Traxxx_server_URL = "https://traxxx.me"

    scrape_tag = "Scraped From Traxxx"  #Tag to be added to scraped scenes.  Set to None to disable
    unmatched_tag = "Missing From Traxxx"  #Tag to be added to scenes that aren't matched at TPDB.  Set to None to disable.
    disambiguate_only = False  # Set to True to run script only on scenes tagged due to ambiguous scraping. Useful for doing manual disambgiuation.  Must set ambiguous_tag for this to work
    verify_aliases_only = False  # Set to True to scrape only scenes that were skipped due to unconfirmed aliases - set confirm_questionable_aliases to True before using
    rescrape_scenes = False  # If False, script will not rescrape scenes previously scraped successfully.  Must set scrape_tag for this to work
    retry_unmatched = False  # If False, script will not rescrape scenes previously unmatched.  Must set unmatched_tag for this to work
    background_size = 'full' # Which size get from API, available options: full, large, medium, small
    debug_mode = False
    scrape_organized = False # If False, script will not scrape scenes set as Organized
    scrape_stash_id = False # If False, script will not scrape scenes that have a stash_id

    #Set what fields we scrape
    set_details = True
    set_date = True
    set_cover_image = True
    set_performers = True
    set_studio = True
    set_tags = True
    set_title = True
    set_url = True

    #ThePornDB API Key
    tpdb_api_key = "" # Add your API Key here eg tbdb_api_key = "myactualapikey"

    #Set what content we add to Stash, if found in ThePornDB but not in Stash
    add_studio = True
    add_tags = False  # Script will still add scrape_tag and ambiguous_tag, if set.  Will also tag ambiguous performers if set to True.
    add_performers = True

    #Disambiguation options
    #The script tries to disambiguate using title, studio, and date (or just filename if parse_with_filename is True).  If this combo still returns more than one result, these options are used.  Set both to False to skip scenes with ambiguous results
    auto_disambiguate = False  #Set to True to try to pick the top result from ThePornDB automatically.  Will not set ambiguous_tag
    manual_disambiguate = False  #Set to True to prompt for a selection.  (Overwritten by auto_disambiguate)
    ambiguous_tag = "ThePornDB Ambiguous"  #Tag to be added to scenes we skip due to ambiguous scraping.  Set to None to disable
    #Disambiguation options for when a specific performer can't be verified
    tag_ambiguous_performers = True  # If True, will tag ambiguous performers (performers listed on ThePornDB only for a single site, not across sites)
    add_ambiguous_performers = False  # If True, will add ambiguous performers (performers listed on ThePornDB only for a single site, not across sites)
    confirm_questionable_aliases = True  #If True, when TPBD lists an alias that we can't verify, manually prompt for config.  Otherwise they are tagged for later reprocessing
    trust_tpbd_aliases = True  #If True, when TPBD lists an alias that we can't verify, just trust TBPD to be correct.  May lead to incorrect tagging

    #Other config options
    parse_with_filename = True  # If True, will query ThePornDB based on file name, rather than title, studio, and date
    dirs_in_query = 0  # The number of directories up the path to be included in the query for a filename parse query.  For example, if the file  is at \performer\mysite\video.mp4 and dirs_in_query is 1, query would be "mysite video."  If set to two, query would be "performer mysite video", etc.
    only_add_female_performers = True  #If True, only female performers are added (note, exception is made if performer name is already in title and name is found on ThePornDB)
    scrape_performers_freeones = True  #If True, will try to scrape newly added performers with the freeones scraper
    get_images_babepedia = True  #If True, will try to grab an image from babepedia before the one from ThePornDB
    include_performers_in_title = True  #If True, performers will be added at the beggining of the title
    male_performers_in_title = False  # If True, male performers and included in the title
    clean_filename = True  #If True, will try to clean up filenames before attempting scrape. Often unnecessary, as ThePornDB already does this
    compact_studio_names = True  # If True, this will remove spaces from studio names added from ThePornDB
    suffix_singlename_performers = False # If True, this will add the studio name to performers with just a single name
    studio_network_suffix = " (Network)"
    proxies = {}  # Leave empty or specify proxy like this: {'http':'http://user:pass@10.10.10.10:8000','https':'https://user:pass@10.10.10.10:8000'}

    #use_oshash = False # Set to True to use oshash values to query NOT YET SUPPORTED

    def loadConfig(self):
        try:  # Try to load configuration.py values
            import configuration
            for key, value in vars(configuration).items():
                if key[0:2] == "__":
                    continue
                if (key == "server_ip" or key == "server_port") and ("<" in value or ">" in value):
                    logging.warning("Please remove '<' and '>' from your server_ip and server_port lines in configuration.py")
                    sys.exit()
                if value is None or isinstance(
                        value, type(vars(config_class).get(key, None))):
                    vars(self)[key] = value
                else:
                    logging.warning("Invalid configuration parameter: " + key, exc_info=config_class.debug_mode)
            return True
        except ImportError:
            logging.error("No configuration found.  Double check your configuration.py file exists.")
            create_config = input("Create configuruation.py? (yes/no):")
            if create_config == 'y' or create_config == 'Y' or create_config == 'Yes' or create_config == 'yes':
                self.createConfig()
            else:
                logging.error("No configuration found.  Exiting.")
                sys.exit()
        except NameError as err:
            logging.error("Invalid configuration.py.  Make sure you use 'True' and 'False' (capitalized)", exc_info=config_class.debug_mode)
            sys.exit()

    def createConfig(self):
        self.server_ip = input("What's your Stash server's IP address? (no port please):")
        self.server_port = input("What's your Stash server's port?:")
        https_input = input("Does your Stash server use HTTPS? (yes/no):")
        self.use_https = False
        if https_input == 'y' or https_input == 'Y' or https_input == 'Yes' or https_input == 'yes':
            self.use_https = True
        self.username = input("What's your Stash server's username? (Just press enter if you don't use one):")
        self.password = input("What's your Stash server's password? (Just press enter if you don't use one):")

        server_configuration = r"""
#Server configuration
use_https = {4} # Set to False for HTTP
server_ip= "{0}"
server_port = "{1}"
username="{2}"
password="{3}"
ignore_ssl_warnings= True # Set to True if your Stash uses SSL w/ a self-signed cert
""".lstrip().format(self.server_ip, self.server_port, self.username, self.password, self.use_https)

        configuration = r"""
# Configuration options
scrape_tag= "Scraped From ThePornDB"  #Tag to be added to scraped scenes.  Set to None to disable
unmatched_tag = "Missing From ThePornDB" #Tag to be added to scenes that aren't matched at TPDB.  Set to None to disable.
disambiguate_only = False # Set to True to run script only on scenes tagged due to ambiguous scraping. Useful for doing manual disambgiuation.  Must set ambiguous_tag for this to work
verify_aliases_only = False # Set to True to scrape only scenes that were skipped due to unconfirmed aliases - set confirm_questionable_aliases to True before using
rescrape_scenes= False # If False, script will not rescrape scenes previously scraped successfully.  Must set scrape_tag for this to work
retry_unmatched = False # If False, script will not rescrape scenes previously unmatched.  Must set unmatched_tag for this to work
background_size = 'full' # Which size get from API, available options: full, large, medium, small
debug_mode = False
scrape_organized = False # If False, script will not scrape scenes set as Organized
scrape_stash_id = False # If False, script will not scrape scenes that have a stash_id

#Set what fields we scrape
set_details = True
set_date = True
set_cover_image = True
set_performers = True
set_studio = True
set_tags = True
set_title = True
set_url = True

#ThePornDB API Key
tpdb_api_key = ""

#Set what content we add to Stash, if found in ThePornDB but not in Stash
add_studio = True  
add_tags = False  # Script will still add scrape_tag and ambiguous_tag, if set.  Will also tag ambiguous performers if set to True.
add_performers = True 

#Disambiguation options
#The script tries to disambiguate using title, studio, and date (or just filename if parse_with_filename is True).  If this combo still returns more than one result, these options are used.  Set both to False to skip scenes with ambiguous results
auto_disambiguate = False  #Set to True to try to pick the top result from ThePornDB automatically.  Will not set ambiguous_tag
manual_disambiguate = False #Set to True to prompt for a selection.  (Overwritten by auto_disambiguate)
ambiguous_tag = "ThePornDB Ambiguous" #Tag to be added to scenes we skip due to ambiguous scraping.  Set to None to disable
#Disambiguation options for when a specific performer can't be verified
tag_ambiguous_performers = True  # If True, will tag ambiguous performers (performers listed on ThePornDB only for a single site, not across sites)
add_ambiguous_performers = False  # If True, will tag ambiguous performers (performers listed on ThePornDB only for a single site, not across sites)
confirm_questionable_aliases = True #If True, when TPBD lists an alias that we can't verify, manually prompt for config.  Otherwise they are tagged for later reprocessing
trust_tpbd_aliases = True #If True, when TPBD lists an alias that we can't verify, just trust TBPD to be correct.  May lead to incorrect tagging

#Other config options
parse_with_filename = True # If True, will query ThePornDB based on file name, rather than title, studio, and date
dirs_in_query = 0 # The number of directories up the path to be included in the query for a filename parse query.  For example, if the file  is at \performer\mysite\video.mp4 and dirs_in_query is 1, query would be "mysite video."  If set to two, query would be "performer mysite video", etc.
only_add_female_performers = True  #If True, only female performers are added (note, exception is made if performer name is already in title and name is found on ThePornDB)
scrape_performers_freeones = True #If True, will try to scrape newly added performers with the freeones scraper
get_images_babepedia = True #If True, will try to grab an image from babepedia before the one from ThePornDB
include_performers_in_title = True #If True, performers will be added at the beggining of the title
male_performers_in_title = False # If True, male performers and included in the title
clean_filename = True #If True, will try to clean up filenames before attempting scrape. Often unnecessary, as ThePornDB already does this
compact_studio_names = True # If True, this will remove spaces from studio names added from ThePornDB
suffix_singlename_performers = False # If True, this will add the studio name to performers with just a single name
proxies={} # Leave empty or specify proxy like this: {'http':'http://user:pass@10.10.10.10:8000','https':'https://user:pass@10.10.10.10:8000'}
# use_oshash = False # Set to True to use oshash values to query NOT YET SUPPORTED
"""
        with open("configuration.py", "w") as f:
            f.write(server_configuration + configuration)
        print("Configuration file created.  All values are currently at defaults.  It is highly recommended that you edit the configuration.py to your liking.  Otherwise, just re-run the script to use the defaults.")
        sys.exit()


def parseArgs(args):
    my_parser = argparse.ArgumentParser(description='Scrape Stash Scenes from Traxxx')

    # Add the arguments
    my_parser.add_argument(
        'query',
        nargs='*',
        default="",
        metavar='query',
        type=str,
        help='Query string to pass to the Stash Scene "Find" box')
    my_parser.add_argument('-d',
                           '--debug',
                           action='store_true',
                           help='enable debugging')
    my_parser.add_argument('-r',
                           '--rescrape',
                           action='store_true',
                           help='rescrape already scraped scenes')
    my_parser.add_argument('-nr',
                           '--no_rescrape',
                           action='store_true',
                           help='do not rescrape already scraped scenes')
    my_parser.add_argument('-ru',
                           '--retry_unmatched',
                           action='store_true',
                           help='retry previously unmatched scenes')
    my_parser.add_argument('-ruo',
                           '--retry_unmatched_only',
                           action='store_true',
                           help='only retry previously unmatched scenes')
    my_parser.add_argument('-no',
                           '--new_only',
                           action='store_true',
                           help='only scan previously unscanned scenes')
    my_parser.add_argument('-ao',
                            '--verify_aliases_only',
                            action='store_true',
                            help='scrape only scenes with performers that need to be verified')
    my_parser.add_argument('-do',
                           '--disambiguate_only',
                           action='store_true',
                           help='scrape only scenes tagged as ambiguous')
    my_parser.add_argument('-max',
                           '--max_scenes',
                           metavar='max_scenes',
                           default=0,
                           type=int,
                           help='maximum number of scenes to scrape')
    my_parser.add_argument(
        '-t',
        '--tags',
        metavar='search_tags',
        type=str,
        default=[],
        action='append',
        help=
        'only match scenes with these tags; repeat once for each required tag')
    my_parser.add_argument(
        '-nt',
        '--not_tags',
        metavar='not_tags',
        type=str,
        default=[],
        action='append',
        help=
        'do not match scenes with these tags; repeat once for each excluded tag'
    )
    my_parser.add_argument(
        '-md',
        '--man_disambiguate',
        action='store_true',
        help=
        'prompt to manually select a scene when a single result isn\'t found')
    my_parser.add_argument(
        '-ad',
        '--auto_disambiguate',
        action='store_true',
        help=
        'automatically  select the top scene when a single result isn\'t found'
    )
    my_parser.add_argument(
        '-mv',
        '--man_verify_aliases',
        action='store_true',
        help=
        'prompt to manually confirm an alias when automatic verification fails'
    )

    # Execute the parse_args() method to collect our args
    parsed_args = my_parser.parse_args(args)
    #Set variables accordingly
    global config
    global max_scenes
    global required_tags
    global excluded_tags
    if parsed_args.debug: config.debug_mode = True
    if parsed_args.rescrape: config.rescrape_scenes = True
    if parsed_args.retry_unmatched: config.retry_unmatched = True
    if parsed_args.retry_unmatched_only:
        config.retry_unmatched = True
        required_tags.append(config.unmatched_tag)
    if parsed_args.new_only:
        config.retry_unmatched = False
        excluded_tags.append(config.ambiguous_tag)
    if parsed_args.no_rescrape: config.rescrape_scenes = False
    if parsed_args.disambiguate_only:
        config.disambiguate_only = True
        config.manual_disambiguate = True
    if parsed_args.man_disambiguate:
        config.manual_disambiguate = True
    if parsed_args.auto_disambiguate:
        config.auto_disambiguate = True
    if parsed_args.man_verify_aliases:
        config.manConfirmAlias = True
    if parsed_args.verify_aliases_only:
        config.verify_aliases_only = True
        config.manConfirmAlias = True
    if parsed_args.max_scenes: max_scenes = parsed_args.max_scenes
    for tag in parsed_args.tags:
        required_tags.append(tag)
    for tag in parsed_args.not_tags:
        excluded_tags.append(tag)
    return parsed_args.query


#Globals
AdultTime_error_count = 0
my_stash = None
channels = []
ENCODING = 'utf-8'
known_aliases = {}
required_tags = []
excluded_tags = []
max_scenes = 0
config = config_class()
api_url = ''


def main(args):
    logging.basicConfig(level=logging.DEBUG)
    try:
        global my_stash
        global channels
        global max_scenes
        global required_tags
        global excluded_tags
        global config
        global api_url
        global AdultTime_error_count
        global AdultTime_headers
        AdultTime_error_count = 0
        config.loadConfig()
        scenes = None
        
        query_args = parseArgs(args)
        if len(query_args) == 1:
            query = "\"" + query_args[0] + "\""
        else:
            query = ' '.join(query_args)

        if not config.debug_mode: logging.getLogger().setLevel("WARNING")

        if config.use_https:
            server = 'https://' + str(config.server_ip) + ':' + str(config.server_port)
        else:
            server = 'http://' + str(config.server_ip) + ':' + str(config.server_port)

        my_stash = StashInterface.stash_interface(server, config.username, config.password, config.ignore_ssl_warnings)

        if len(config.proxies) > 0: my_stash.setProxies(config.proxies)

        if config.ambiguous_tag:
            my_stash.getTagByName(config.ambiguous_tag, True)
        if config.scrape_tag:
            scrape_tag_id = my_stash.getTagByName(config.scrape_tag, True)["id"]
        if config.unmatched_tag:
            unmatched_tag_id = my_stash.getTagByName(config.unmatched_tag, True)["id"]
        config.unconfirmed_alias = my_stash.getTagByName("Traxxx Unconfirmed Alias", True)["name"]

        findScenes_params = {}
        findScenes_params['filter'] = {'q': query, 'sort': "created_at", 'direction': 'DESC'}
        findScenes_params['scene_filter'] = {}
        if max_scenes != 0: findScenes_params['max_scenes'] = max_scenes

        if config.disambiguate_only:  #If only disambiguating scenes
            required_tags.append(config.ambiguous_tag)
        if config.verify_aliases_only:  #If only disambiguating aliases
            required_tags.append(config.unconfirmed_alias)
        if not config.retry_unmatched:  #If not retrying unmatched scenes
            excluded_tags.append(config.unmatched_tag)
        if not config.rescrape_scenes:  #If only scraping unscraped scenes
            excluded_tags.append(config.scrape_tag)

        my_stash.waitForIdle()  #Wait for Stash to idle before scraping

        #Set our filter to require any required_tags
        if len(required_tags) > 0:
            findScenes_params_incl = copy.deepcopy(findScenes_params)
            required_tag_ids = []
            for tag_name in required_tags:
                tag = my_stash.getTagByName(tag_name, False)
                if tag:
                    required_tag_ids.append(tag["id"])
                else:
                    logging.error("Did not find tag in Stash: " + tag_name, exc_info=config.debug_mode)
            
            findScenes_params_incl['scene_filter']['tags'] = { 'modifier': 'INCLUDES','value': [*required_tag_ids] }
            findScenes_params_incl['scene_filter']['path'] = {'modifier': 'INCLUDES', 'value':'AdultTime'}
            if (not config.scrape_stash_id): # include only scenes without stash_id
                findScenes_params_incl['scene_filter']['stash_id'] = { 'modifier': 'IS_NULL', 'value': 'none' }
            if (not config.scrape_organized): # include only scenes that are not organized
                findScenes_params_incl['scene_filter']['organized'] = False
            
            if len(excluded_tags) > 0:
                print("Getting Scenes With Required Tags")
            scenes_with_tags = my_stash.findScenes(**findScenes_params_incl)
            scenes = scenes_with_tags

        #Set our filter to exclude any excluded_tags
        if len(excluded_tags) > 0:
            findScenes_params_excl = copy.deepcopy(findScenes_params)
            excluded_tag_ids = []
            for tag_name in excluded_tags:
                tag = my_stash.getTagByName(tag_name, False)
                if tag:
                    excluded_tag_ids.append(tag["id"])
                else:
                    logging.error("Did not find tag in Stash: " + tag_name, exc_info=config.debug_mode)
            
            findScenes_params_excl['scene_filter']['tags'] = { 'modifier': 'EXCLUDES', 'value': [*excluded_tag_ids] }
            findScenes_params_excl['scene_filter']['path'] = {'modifier': 'INCLUDES', 'value':'AdultTime'}
            if (not config.scrape_stash_id): # include only scenes without stash_id
                findScenes_params_excl['scene_filter']['stash_id'] = { 'modifier': 'IS_NULL', 'value': 'none' }
            if (not config.scrape_organized): # include only scenes that are not organized
                findScenes_params_excl['scene_filter']['organized'] = False

            if len(required_tags) > 0:
                print("Getting Scenes Without Excluded Tags")
            scenes_without_tags = my_stash.findScenes(**findScenes_params_excl)
            scenes = scenes_without_tags

        if len(excluded_tags) == 0 and len(
                required_tags) == 0:  #If no tags are required or excluded
            findScenes_params_filtered = copy.deepcopy(findScenes_params)
            if (not config.scrape_stash_id): # include only scenes without stash_id
                findScenes_params_filtered['scene_filter']['stash_id'] = { 'modifier': 'IS_NULL', 'value': 'none' }
            if (not config.scrape_organized): # include only scenes that are not organized
                findScenes_params_filtered['scene_filter']['organized'] = False
            scenes = my_stash.findScenes(**findScenes_params_filtered)

        if len(required_tags) > 0 and len(excluded_tags) > 0:
            scenes = [ scene for scene in scenes_with_tags if scene in scenes_without_tags]  #Scenes that exist in both
        
        if (not config.scrape_organized):
            print("Skipped Organized scenes")
        if (not config.scrape_stash_id):
            print("Skipped scenes with a stash_id")
        print("Scenes to scrape", str(len(scenes)))

        api_url = get_api()

        for scene in scenes:
            scrapeScene(scene)

        print("Success! Finished.")

    except Exception as e:
        logging.error("""Something went wrong.  Have you:
        • Checked to make sure you're running the "development" branch of Stash, not "latest"?
        • Checked that you can connect to Stash at the same IP and port listed in your configuration.py?
        If you've check both of these, run the script again with the --debug flag.  Then post the output of that in the Discord and hopefully someone can help.
        """, exc_info=config.debug_mode)


if __name__ == "__main__":
    main(sys.argv[1:])
