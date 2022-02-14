#!/usr/bin/python3

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

custom_sceneQuery = None
if Path(__file__).with_name('custom_sceneQuery.py').is_file():
    from custom_sceneQuery import sceneQuery as custom_sceneQuery

###########################################################
#CONFIGURATION OPTIONS HAVE BEEN MOVED TO CONFIGURATION.PY#
###########################################################

#Metadataapi API settings
traxxx_sleep = 1  # time to sleep before each API req
traxxx_ua = "stashpy/1.0.0"  # user agent
traxxx_headers = {
    'User-Agent': traxxx_ua,
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
    string = string.replace(',', '')
    string = string.replace('.', '')
    string = string.replace(" & ", ' ')
    string = string.replace(" and ", ' ')
    string = string.replace("nude girls ", ' ')
    string = string.replace("girl girl ", ' ')
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

def scrubScene(scene, dirs, file_name):
    scene_title = file_name
    original_title = scene['title']
    
    date_search = re.search('.(\d{2}).(\d{2}).(\d{2}).[A-z]', scene_title, re.IGNORECASE)
    if date_search:
        date = "20" + date_search.group(1) + "-" + date_search.group(2) + "-" + date_search.group(3)
        if scene['date'] is None or scene['date'] == "" and file_name == scene['title']: 
            scene['date'] = date

        title_search = re.search("(\d{2}).(\d{2}).(\d{2}).(.+?).XXX", scene_title, re.IGNORECASE)
        if title_search and file_name == scene['title']:
            title =  title_search.group(4)
            title_search = re.search("(\d{2}).(.+?)$", title, re.IGNORECASE)
            title_search2 = re.search("(\d{2}).(\d{2}).(\d{2}).(\d{2}).(.+?).XXX", scene_title, re.IGNORECASE)
            if title_search and title_search2:
                scene['title'] = re.sub('\.', ' ', title_search.group(2))
            else:
                scene['title'] = re.sub('\.', ' ', title)
        else:
            title_search = re.search("(.+?).(\d{2}).(\d{2}).(\d{2}).(.+?)$", scene_title, re.IGNORECASE)
            if title_search:
                scene['title'] = re.sub('\.', ' ', title_search.group(5))
    else:
        if scene['date'] is None and file_name == scene['title']:
            episode2_search = re.search('.E(\d{2}).', scene_title, re.IGNORECASE)
            episode3_search = re.search('.E(\d{3}).', scene_title, re.IGNORECASE)
            
            if episode3_search:
                title_search = re.search(".E(\d{3}).(.+?).XXX", scene_title, re.IGNORECASE)
                if title_search:
                    scene['title'] = re.sub('\.', ' ', title_search.group(2))
            elif episode2_search:
                title_search = re.search(".E(\d{2}).(.+?).XXX", scene_title, re.IGNORECASE)
                if title_search:
                    scene['title'] = re.sub('\.', ' ', title_search.group(2))

    if len(scene_title) <= 1:
        scene_title = file_name
    else:
        scene['title'] = scrubFileName(scene['title'])

    if keyIsSet(scene, ["studio", "name"]):
        scene['studio']['name'] = findChannel(scene['studio']['name'])
    else:
        if dirs:
            scene['studio'] = {}
            scene['studio']['name'] = findChannel(dirs[-3])
            if scene['studio']['name'].lower() == "sis":
                scene['studio']['name'] = "SisPorn"
    return scene        


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


def listToLower(input_list):
    output_list = []
    for item in input_list:
        if isinstance(item, str):
            output_list.append(item.lower())
        else:
            output_list.append(item)
    return output_list

#Script-specific functions
def getChannels():  # Scrapes Traxxx and Return an array of network as results, or None
    global traxxx_headers
    global traxxx_error_count
    url = config.traxxx_server_URL + "/api/channels?limit=99999"
    
    try:
        #time.sleep(traxxx_sleep)  # sleep before every request to avoid being blocked
        result = requests.get(url, proxies=config.proxies, timeout=(3, 5), headers=traxxx_headers)
        traxxx_error_count = 0
        if result.status_code >= 400:
            logging.error('Traxxx HTTP Error: %s' % result.status_code)
            return None
        return result.json()["entities"]
    except ValueError:
        logging.error("Error communicating with Traxxx")
        traxxx_error_count = traxxx_error_count + 1
        if traxxx_error_count > 3:
            logging.error("Traxxx seems to be down.  Exiting.")
            sys.exit()
        return None

def getChannel(channel_id):
    global channels
    for channel in channels:
        if channel['id'] ==  channel_id:
            return channel
            break
    
    return None

def getChannelByName(channel_name):
    global channels
    channel_name = channel_name.replace("Bang.", "").replace("'", "").lower()
    for channel in channels:
        if channel['name'].replace("'", "").lower() ==  channel_name:
            return channel
            break
    
    return None

def findChannel(channel_name):
    global channels
    channel_name = channel_name.replace("Bang.", "").replace("'", "").lower()
    for channel in channels:
        if channel['name'].replace("'", "").lower() ==  channel_name:
            channel_name = channel['name']
            break
        if channel['slug'].lower() ==  channel_name:
            channel_name = channel['name']
            break
    
    return channel_name

def createStashPerformerData(traxxx_performer):  #Creates stash-compliant data from raw data provided by traxxx
    stash_performer = {}
    if keyIsSet(traxxx_performer, ["name"]):
        if " " in traxxx_performer["name"]:
            stash_performer["name"] = traxxx_performer["name"]
        else:
            stash_performer["name"] = traxxx_performer["name"] + " (" + traxxx_performer['studio_name'] + ")"

    if keyIsSet(traxxx_performer, ["dateOfBirth"]):
        stash_performer["birthdate"] = traxxx_performer["dateOfBirth"]
        
    if keyIsSet(traxxx_performer, ["placeOfResidence", "country", "name"]):
        stash_performer["country"] = traxxx_performer["placeOfResidence"]["country"]["name"]
    if keyIsSet(traxxx_performer, ["height"]):
        stash_performer["height"] = str(traxxx_performer["height"])
    #if keyIsSet(traxxx_performer, ["eyes"]):
    #    stash_performer["eyecolor"] = traxxx_performer["eyes"]
    #if keyIsSet(traxxx_performer, ["hairColor"]):
    #    stash_performer["haircolor"] = traxxx_performer["hairColor"]
    if keyIsSet(traxxx_performer, ["tattoos"]):
        stash_performer["tattoos"] = traxxx_performer["tattoos"]
    if keyIsSet(traxxx_performer, ["piercings"]):
        stash_performer["piercings"] = traxxx_performer["piercings"]
    if keyIsSet(traxxx_performer, ["avatar", "path"]):
        stash_performer["image"] = config.traxxx_server_URL + "/media/" + traxxx_performer["avatar"]["path"]
    if keyIsSet(traxxx_performer, ["gender"]):
        if traxxx_performer["gender"] == "male":
            stash_performer["gender"] = 'MALE'
        if traxxx_performer["gender"] == "female":
            stash_performer["gender"] = 'FEMALE'
        if traxxx_performer["gender"] == "transgender male":
            stash_performer["gender"] = 'TRANSGENDER_MALE'
        if traxxx_performer["gender"] == "transgender female":
            stash_performer["gender"] = 'TRANSGENDER_FEMALE'
        if traxxx_performer["gender"] == "intersex":
            stash_performer["gender"] = 'INTERSEX'
    return stash_performer

def createStashStudioData(traxxx_studio):  # Creates stash-compliant data from raw data provided by traxxx
    stash_studio = {}
    print(traxxx_studio)
    temp_studio = getChannelByName(traxxx_studio['name'])
    if temp_studio is not None:
        traxxx_studio = temp_studio
        
    parent_scraped_studio = None
    if keyIsSet(traxxx_studio, ['parent']) and traxxx_studio["parent"] is not None:
        parent_scraped_studio = traxxx_studio["parent"]
    
    if parent_scraped_studio is not None:
        if parent_scraped_studio['type'] == "network" and config.studio_network_suffix:
            parent_scraped_studio["name"] = parent_scraped_studio["name"] + config.studio_network_suffix

        parent_stash_studio = my_stash.getStudioByName(parent_scraped_studio['name'])
        if parent_stash_studio is not None:
            stash_studio["parent_id"] = parent_stash_studio["id"]
        else:
            stash_studio["parent_id"] = my_stash.addStudio((createStashStudioData(parent_scraped_studio)))


    if config.compact_studio_names:
        stash_studio["name"] = traxxx_studio["name"].replace(' ', '')
    else:
        stash_studio["name"] = traxxx_studio["name"]
    
    if keyIsSet(traxxx_studio, ['description']) and traxxx_studio["description"] is not None:
        stash_studio["details"] = traxxx_studio["description"]   

    if keyIsSet(traxxx_studio, ['"url"']):
        stash_studio["url"] = traxxx_studio["url"]
    
    if keyIsSet(traxxx_studio, ['parent']) and traxxx_studio["parent"] is not None:
        parentName = traxxx_studio["parent"]["name"]
        if traxxx_studio["parent"]['type'] == "network" and config.studio_network_suffix:
            parentName = parentName + config.studio_network_suffix 
        parent = my_stash.getStudioByName(parentName)
        if parent is not None:
            stash_studio["parent_id"] = parent["id"]
    if keyIsSet(traxxx_studio, ['"logo"']) and traxxx_studio["logo"] is not None:
        stash_studio["image"] = config.traxxx_server_URL + "/img/logos/" + traxxx_studio["logo"]
    
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

def getPerformer(name, performer_id):
    global traxxx_headers
    global traxxx_error_count
    search_url = config.traxxx_server_URL + "/api/actors?limit=3&q=" + urllib.parse.quote(name)
    data_url_prefix = config.traxxx_server_URL + "/api/actors/"
    try:
        time.sleep(traxxx_sleep)  # sleep before every request to avoid being blocked
        result = requests.get(search_url,proxies=config.proxies, timeout=(3, 5), headers=traxxx_headers)
        traxxx_error_count = 0
        if result.status_code >= 400:
            logging.error('Traxxx HTTP Error: %s' % result.status_code)
            return None
        if next(iter(result.json().get("actors", [{}])), {}).get("id", None):
            if performer_id is None:
                performer_id = result.json()["actors"][0]["id"]
            return requests.get(data_url_prefix + str(performer_id), proxies=config.proxies).json()["actor"]
        else:
            return None
    except ValueError:
        logging.error("Error communicating with Traxxx")
        traxxx_error_count = traxxx_error_count + 1
        if traxxx_error_count > 3:
            logging.error("Traxxx seems to be down.  Exiting.")
            sys.exit()

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
    global traxxx_headers
    global traxxx_error_count
    if custom_sceneQuery is not None:
        query = custom_sceneQuery(query)
    url = config.traxxx_server_URL + "/api/scenes?limit=3&q=" + urllib.parse.quote(query.replace(" ", "."))
    result = None
    try:
        time.sleep(traxxx_sleep)  # sleep before every request to avoid being blocked
        result = requests.get(url, proxies=config.proxies, timeout=(3, 15), headers=traxxx_headers)
        traxxx_error_count = 0
        if result.status_code >= 400:
            logging.error('Traxxx HTTP Error: %s' % result.status_code)
            return None
        return result.json()["scenes"]
    except ValueError:
        logging.error("Error communicating with Traxxx")
        traxxx_error_count = traxxx_error_count + 1
        if traxxx_error_count > 3:
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

def cleanResults(scene, scraped_data):
    clean_data = []

    for scraped_scene in scraped_data:
        first_item = scraped_scene

        if keyIsSet(scene, ["studio", "name"]) and keyIsSet(first_item, ['entity', 'name']):
            first_item_studio = first_item['entity']['name']
            scene_studio = scene['studio']['name']
            
            if (stripString(first_item_studio) == stripString(scene_studio)):
                clean_data.append(first_item)
            elif stripString(scene_studio) == "pornmegaload" or stripString(scene_studio) == "xlgirls":
                if stripString(first_item_studio) == "xlgirls" or stripString(first_item_studio) == "scoreland" or stripString(first_item_studio) == "18eighteen" or stripString(first_item_studio) == "50plusmilfs" or stripString(first_item_studio) == "60plusmilfs" or stripString(first_item_studio) == "40somethingmag":
                    clean_data.append(first_item)
            elif stripString(scene_studio) == "legalporno" or stripString(scene_studio) == "analvids" or stripString(scene_studio) == "ddfbusty" or stripString(scene_studio) == "handsonhardcore" or stripString(scene_studio) == "pornworld" or stripString(scene_studio) == "eurogirlsongirls" or stripString(scene_studio) == "houseoftaboo":
                if stripString(first_item_studio) == "legalporno" or stripString(first_item_studio) == "analvids" or stripString(first_item_studio) == "ddfbusty" or stripString(first_item_studio) == "handsonhardcore" or stripString(first_item_studio) == "pornworld" or stripString(first_item_studio) == "eurogirlsongirls" or stripString(first_item_studio) == "houseoftaboo":
                    clean_data.append(first_item)
                
            #else:
            #    print(stripString(first_item_studio) + ' == ' + stripString(scene_studio))

    return clean_data

def autoDisambiguateResults(scene, scrape_query, scraped_data):
    matched_scene = None
    matched_item_name = ""
    
    for scraped_scene in scraped_data:
        match_url = False
        match_studio = False
        close_studio = False
        match_date = False
        match_ratio = 0
        
        first_item = scraped_scene
        first_item_name = ""
        studio_name = ""
        if keyIsSet(scene, ["studio", "name"]) and keyIsSet(first_item, ['entity', 'name']):
            studio_name = scene['studio']['name']
            match_studio = (stripString(first_item['entity']['name']) == stripString(scene['studio']['name']))
            
            if (stripString(first_item['entity']['name']) != stripString(scene['studio']['name'])):
                close_studio = True
            
            first_item_name =  first_item_name + " " + first_item['entity']['name']

        if match_studio == False:
            if keyIsSet(scene, ["studio", "name"]) and keyIsSet(first_item, ['entity', 'parent', 'name']):
                studio_name = scene['studio']['name']
                match_studio = (stripString(first_item['entity']['parent']['name']) == stripString(scene['studio']['name']))
            
                if (stripString(first_item['entity']['parent']['name']) != stripString(scene['studio']['name'])):
                    close_studio = True
            
                first_item_name =  first_item_name + " " + first_item['entity']['parent']['name']


        if scene['date'] and first_item['date']:
            match_date = (first_item['date'].split('T')[0] == scene['date'])
            first_item_name =  first_item_name + " " + first_item['date'].split('T')[0]
            
        if scene['date'] is None:
            match_date = True

        performer_names = []
        if first_item['actors']:
            for scraped_performer in first_item["actors"]:
                not_female = False
                 
                if keyIsSet(scraped_performer, ["gender"]) and scraped_performer["gender"] != 'female':
                    not_female = True

                if (not_female):
                    continue  # End current loop on male performers not in path

                performer_names.append(scraped_performer['name'])

            first_item_name =  first_item_name + " " + ' '.join(map(str, performer_names))

        if scene['url'] and first_item['url']:
            match_url = scene['url'] == first_item['url'] 

        
        if scene['title'] and first_item['title']:
            title = first_item['title']
            scene_title = scene['title']
            if (studio_name == "Abby Winters"):
                title = title.replace('Nude Girls', '')
                title = title.replace('Video Masturbation', '')
                title = title.replace('Girl Girl', '')
                
                scene_title = scene_title.replace('Nude Girls', '')
                scene_title = scene_title.replace('Video Masturbation', '')
                scene_title = scene_title.replace('Girl Girl', '')
            
            temp_ratio = difflib.SequenceMatcher(None, 
                stripString(title), 
                stripString(scene_title)).ratio()
            if match_ratio < temp_ratio:
                match_ratio = temp_ratio
            
            temp_ratio = difflib.SequenceMatcher(None, 
                stripString(' '.join(map(str, performer_names)) + title), 
                stripString(scene_title)).ratio()
            if match_ratio < temp_ratio:
                match_ratio = temp_ratio
            
            temp_ratio = difflib.SequenceMatcher(None, 
                stripString(' '.join(map(str, performer_names))), 
                stripString(scene_title)).ratio()
            if match_ratio < temp_ratio:
                match_ratio = temp_ratio
            
            first_item_name =  first_item_name + " " + title
                
            temp_ratio = difflib.SequenceMatcher(None, 
                stripString(first_item_name), 
                stripString(scrape_query)).ratio()
            
            if first_item['shootId']:
                if first_item['shootId'] in scene_title:
                    temp_ratio = 1
                    
            if match_ratio < temp_ratio:
                match_ratio = temp_ratio


            first_item_name =  first_item_name + " (" + str(match_ratio) + ")"

        if match_url == True:
            print("matched url")
            matched_scene = first_item
            matched_item_name = first_item_name

        # print("Test Data For:     " + first_item_name)    
        if match_studio == True and match_date == True and match_ratio > 0.65:
            matched_scene = first_item
            matched_item_name = first_item_name

        if match_studio == True and scene['date'] is None:
            print(first_item_name)

        if match_studio == True and match_ratio > 0.9:
            first_item['date'] = scene['date']
            matched_scene = first_item
            matched_item_name = first_item_name
        elif match_studio == True and len(scraped_data) == 1:
            new_item = copy.deepcopy(first_item)
            new_item['date'] = scene['date']
            scraped_data.append(new_item)
        
        if close_studio == True and match_date == True and match_ratio > 0.99:
            matched_scene = first_item
            matched_item_name = first_item_name
        elif close_studio == True and len(scraped_data) == 1:
            print ("close_studio " + str(match_ratio))
            print(first_item_name);
            new_item = copy.deepcopy(first_item)
            new_item['date'] = scene['date']
            scraped_data.append(new_item)

        # print(first_item_name)
        
    if matched_scene is None:
        if len(scraped_data) == 1 and not config.manual_disambiguate:
            return []
        else:
            return scraped_data

    print("Found Data For:    " + matched_item_name)
    new_data = []
    new_data.append(matched_scene)
    return new_data

def manuallyDisambiguateResults(scraped_data):
    print("Found ambiguous result.  Which should we select?:")
    for index, scene in enumerate(scraped_data):
        print(index + 1, end=': ')
        if keyIsSet(scene, ['entity', 'name']):
            print(scene['entity']['name'], end=" ")
        if keyIsSet(scene, ['date']) and scene['date']: print(scene['date'].split('T')[0], end=" ")
        if keyIsSet(scene, ['title']): print(scene['title'], end=" ")
        if keyIsSet(scene, ['shootId']): print('[' + scene['shootId'] + ']', end=" ")
        if keyIsSet(scene, ['actors']):
            performer_names = []
            for scraped_performer in scene["actors"]:
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


def areAliases(first_performer, second_performer, site=None):
    if first_performer.lower() == second_performer.lower():  #No need to conduct checks if they're the same
        return True

    global my_stash
    global known_aliases
    global config
    if config.compact_studio_names and site:
        site = site.replace(' ', '')

    first_performer_aliases = [first_performer]
    if known_aliases.get(first_performer, None):
        first_performer_aliases = first_performer_aliases + known_aliases.get(first_performer, None)
    second_performer_aliases = [second_performer]
    if known_aliases.get(second_performer, None):
        second_performer_aliases = second_performer_aliases + known_aliases.get(second_performer, None)
    ##build aliases of both first/second performer
    #First performer
    result = my_stash.getPerformerByName(first_performer)
    if result and keyIsSet(result, "aliases"):  #Add Stash Aliases
        first_performer_aliases = list(set(first_performer_aliases + result["aliases"]))
    result = my_stash.scrapePerformerFreeones(first_performer)
    if result and keyIsSet(result, "aliases"):  #Add Freeones Aliases
        first_performer_aliases = list(set(first_performer_aliases + result["aliases"]))
    result = getPerformer(first_performer)
    if result and keyIsSet(result, "aliases"):  #Add TPBD Aliases
        first_performer_aliases = list(set(first_performer_aliases + result["aliases"]))
    #Second Performer
    result = my_stash.getPerformerByName(second_performer)
    if result and keyIsSet(result, "aliases"):  #Add Stash Aliases
        second_performer_aliases = list(set(second_performer_aliases + result["aliases"]))
    result = my_stash.scrapePerformerFreeones(second_performer)
    if result and keyIsSet(result, "aliases"):  #Add Freeones Aliases
        second_performer_aliases = list(set(second_performer_aliases + result["aliases"]))
    result = getPerformer(second_performer)
    if result and keyIsSet(result, "aliases"):  #Add TPBD Aliases
        second_performer_aliases = list(set(second_performer_aliases + result["aliases"]))
    #check if one is an alias of another, but don't compare aliases
    if first_performer in second_performer_aliases or second_performer in first_performer_aliases:
        return True
    first_performer = first_performer + " (" + site + ")"
    second_performer = second_performer + " (" + site + ")"
    if first_performer in second_performer_aliases or second_performer in first_performer_aliases:
        return True
    return False


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

    if not config.parse_with_filename:
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
        scene = scrubScene(scene, dirs, file_name)

        if keyIsSet(scene, ["studio", "name"]):
            scrape_query = scrape_query + ' ' + cleanString(scene['studio']['name'])

        if scene['date']:
            scrape_query = scrape_query + ' ' + scene['date']
            
        scrape_query = scrape_query + ' ' +  cleanString(scene['title'])

    return '' if scrape_query is None else str(scrape_query.strip())


def scrapeScene(scene):
    global my_stash
    global config
    try:
        scene_data = my_stash.createSceneUpdateData(scene)  # Start with our current data as a template
        scrape_query = ""
        scraped_data = None
        #if config.use_oshash and scene['oshash']:
        #    scraped_data = sceneHashQuery(scene['oshash'])
        if not scraped_data:
            scrape_query = getQuery(scene)
            scraped_data = sceneQuery(scrape_query)
            if keyIsSet(scene, ["date"]):
                scene_data['date'] = scene['date']
            if keyIsSet(scene, ["studio", "name"]):
                stash_studio = my_stash.getStudioByName(scene['studio']['name'])
                if stash_studio:
                    scene_data["studio_id"] = stash_studio["id"]
                elif config.add_studio:
                    # Add the Studio to Stash
                    print("Did not find " + scene['studio']['name'] + " in Stash.  Adding Studio.")
                    scene_data["studio_id"] = my_stash.addStudio((createStashStudioData(scene['studio'])))
            scene_data['title'] = scene['title']
        if not scraped_data:
            print("No data found for: [{}]".format(scrape_query))
            scene_data["tag_ids"].append(my_stash.getTagByName(config.unmatched_tag)['id'])
            my_stash.updateSceneData(scene_data)
            return None

        print("Grabbing Data For: " + scrape_query)

        scraped_data = cleanResults(scene, scraped_data)
        
        if len(scraped_data) > 0:  #Auto disambiguate
            scraped_data = autoDisambiguateResults(scene, scrape_query, scraped_data)
            #print("Auto disambiguated")
            
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
            updateSceneFromScrape(scene_data, scraped_scene, scene['path'])
            print("Success")
        else:
            scene_data["tag_ids"].append(
                my_stash.getTagByName(config.unmatched_tag)['id'])
            my_stash.updateSceneData(scene_data)
            print("No data found for: [{}]".format(scrape_query))
    except Exception as e:
        logging.error("Exception encountered when scraping '" + scrape_query, exc_info=config.debug_mode)


def manConfirmAlias(scraped_performer, site):  #Returns scraped_performer if response is positive, None otherwise.  If Always or Site are selected, scraped_performer is updated to include a new alias
    global known_aliases
    global config
    if config.compact_studio_names:
        site = site.replace(' ', '')
    response = input("Found " + scraped_performer['name'] + " as a performer in scene, which TPBD indicates is an alias of " + scraped_performer['parent']['name'] + ".  Should we trust that? (Y)es / (N)o / (A)lways / Always for this (S)ite:")
    if response == 'y' or response == 'Y' or response == 'Yes' or response == 'yes':
        return scraped_performer
    elif response == 'a' or response == 'A' or response == 'always' or response == 'Always':
        #Update our global var
        known_alias_entry = known_aliases.get(scraped_performer['parent']['name'], None)
        if known_alias_entry:
            known_aliases[scraped_performer['parent']['name']].append(scraped_performer['name'])
        else:
            known_aliases[scraped_performer['parent']['name']] = [scraped_performer['name']]
        if keyIsSet(scraped_performer, ["parent", "aliases"]):
            scraped_performer["parent"]['aliases'].append(scraped_performer['name'])
        else:
            scraped_performer["parent"]['aliases'] = [scraped_performer['name']]
        return scraped_performer
    elif response == 's' or response == 'S' or response == 'Site' or response == 'site':
        #Update our global var
        known_alias_entry = known_aliases.get(scraped_performer['parent']['name'], None)
        if known_alias_entry:
            known_aliases[scraped_performer['parent']['name']].append(scraped_performer['name'] + " (" + site + ")")
        else:
            known_aliases[scraped_performer['parent']['name']] = [scraped_performer['name'] + " (" + site + ")"]
        if keyIsSet(scraped_performer, ["parent", "aliases"]):
            scraped_performer["parent"]['aliases'].append(scraped_performer['name'] + " (" + site + ")")
        else:
            scraped_performer["parent"]['aliases'] = [scraped_performer['name'] + " (" + site + ")"]
        return scraped_performer
    return None


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
            scene_data["details"] = scraped_scene["description"]  #Add details
        if config.set_date and keyIsSet(scraped_scene, "date"):
            scene_data["date"] = scraped_scene["date"] #.split('T')[0]  #Add date
        if config.set_url: scene_data["url"] = scraped_scene["url"]  #Add URL
        if config.set_cover_image and keyIsSet(scraped_scene, ["poster", "path"]):  #Add cover_image
            cover_image = getJpegImage(config.traxxx_server_URL + "/media/" + scraped_scene["poster"]['path'])
            if cover_image:
                image_b64 = base64.b64encode(cover_image)
                stringbase = str(image_b64)
                scene_data["cover_image"] = stash_b64_header + image_b64.decode(ENCODING)

        if keyIsSet(scraped_scene, "entity"):
            scraped_studio = scraped_scene['entity']
        
        # Add Studio to the scene
        if config.set_studio and keyIsSet(scraped_scene, "entity"):
            studio_id = None
            scraped_studio = scraped_scene['entity']
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
                if (keyIsSet(tag, "name")):
                    tags_to_add.append({'tag': tag['name']})

        # Add performers to scene
        if config.set_performers and keyIsSet(scraped_scene, "actors"):
            scraped_performer_ids = []
            for scraped_performer in scraped_scene["actors"]:
                not_female = False

                if keyIsSet(scraped_performer, ["gender"]) and scraped_performer["gender"] == 'male':
                    not_female = True

                if (config.only_add_female_performers and not_female):
                    continue  # End current loop on male performers not in path

                performer_id = None
                performer_name = scraped_performer['name']
                search_name = performer_name                 
                stash_performer = my_stash.getPerformerByName(performer_name)
                add_this_performer = False
                if not stash_performer and not " " in performer_name:
                    search_name = performer_name + " (" + scraped_studio['name'] + ")"
                    stash_performer = my_stash.getPerformerByName(search_name)
                if stash_performer:
                    performer_id = stash_performer["id"]  #If performer already exists, use that
                    if config.male_performers_in_title or not not_female:
                        performer_names.append(performer_name)  #Add to list of performers in scene
                else:  #If site name does not match someone in Stash and TPBD has a linked parent
                    # Add performer if we meet relevant requirements
                    if config.add_performers:
                        print("Did not find " + performer_name +
                          " in Stash.  Adding performer.")
                        scraped_performer = getPerformer(performer_name, scraped_performer['id'])
                        scraped_performer["studio_name"] = scraped_studio['name']
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
            if keyIsSet(scraped_scene, "title"):
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
    traxxx_server_URL = "https://traxxx.me"

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
traxxx_error_count = 0
my_stash = None
channels = []
ENCODING = 'utf-8'
known_aliases = {}
required_tags = []
excluded_tags = []
max_scenes = 0
config = config_class()


def main(args):
    logging.basicConfig(level=logging.DEBUG)
    try:
        global my_stash
        global channels
        global max_scenes
        global required_tags
        global excluded_tags
        global config
        global traxxx_error_count
        global traxxx_headers
        traxxx_error_count = 0
        config.loadConfig()
        scenes = None
        #if config.tpdb_api_key != "":
        #    tpdb_headers['Authorization'] = 'Bearer ' + config.tpdb_api_key
        #    logging.info('API Key found for TPDB')
        #else:
        #    print("TPDB API Key not set. Exiting.")
        #    return

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
            unmatched_tag_id = my_stash.getTagByName(config.unmatched_tag,
                                                     True)["id"]
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
            # findScenes_params_incl['scene_filter']['path'] = {'modifier': 'EXCLUDES', 'value':'AdultTime'}
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
            findScenes_params_excl['scene_filter']['path'] = {'modifier': 'EXCLUDES', 'value':'AdultTime'}
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

        channels = getChannels()
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
