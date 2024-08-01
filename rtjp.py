#!/usr/bin/env python3

import argparse
import datetime
import json
import dill
import sys
from requests import Session
from requests.auth import HTTPBasicAuth
from zeep import Client, Settings
from zeep.cache import SqliteCache
from zeep.transports import Transport
from zeep.helpers import serialize_object
import xml.etree.ElementTree as etree

# See National Rail Enquiries Licence Request email
user = '<my rtjp username>'
password = '<my rtjp password>'

# WSDL location
wsdl_url = 'https://ojp.nationalrail.co.uk/webservices/jpdlr.wsdl'
cache_path = '/path/to/rtjp_zeep_cache.sqlite.db'
cache_life_seconds = 60*60*24*31

# Desired travel times:
#  outward on 08:05 only
#  inward on 16:00 or 16:29 or 16:30
want_from = 'ABD'
want_to   = 'ARB'
want_outward_hour = 8
want_outward_min  = 5
want_inward_hour  = 16
want_fare_class   = 'STANDARD'

# Configuration
debug = False


def remove_keys_recursively(dict_obj, keys):
    """ Traverses the given dict_obj and removes all any keys
    whose name appears in 'keys' (which can be a list of
    key names, or it can be a string for a single key). """
    for key in list(dict_obj.keys()):
        if not isinstance(dict_obj, dict):
            continue
        elif key in keys:
            dict_obj.pop(key, None)
        elif isinstance(dict_obj[key], dict):
            remove_keys_recursively(dict_obj[key], keys)
        elif isinstance(dict_obj[key], list):
            for item in dict_obj[key]:
                remove_keys_recursively(item, keys)
    return


def create_client(user, password):
    """ Open a connection to the service, download the WSDL
    if not already cached, and return the client object. """

    # Create a HTTP session with Basic authentication
    session = Session()
    session.auth = HTTPBasicAuth(user, password)

    # Determine the path to the WSDL cache
    cache = SqliteCache(path=cache_path, timeout=cache_life_seconds)

    # Create the transport using the HTTP session with the given cache
    transport = Transport(session=session, cache=cache)

    # Client settings
    #  currently turn off strict validation of XML otherwise it
    #  complains about missing items.
    settings = Settings(strict=False)

    # Open the client connection
    client = Client(wsdl_url, transport=transport, settings=settings)
    return client


def save_response_to_file(tomorrow, resp):
    """ Save the response for the given day into a file. """

    with open(f'response_{tomorrow}.dill', 'wb') as fd:
        dill.dump(resp, fd)


def load_response_from_file(tomorrow):
    """ Load the response for the given day (str: YYYY-MM-DD)
    from a pickle file. """

    response_file = f'response_{tomorrow}.dill'
    with open(response_file, 'rb') as fd:
        resp = dill.load(fd)
    if debug:
        print('LOADED RESPONSE FROM FILE %s WITH CONTENT: %s' % (response_file, resp.keys()))
    return resp


def parse_response(resp):
    """ Print out the train and fare details from the given response
    which should be a dict that has no XML. """

    bulletin = ''
    prev_time_str = ''
    for journey in resp['outwardJourney']:
        journey_time = journey['timetable']['scheduled']['departure']
        if journey_time.hour != want_outward_hour or journey_time.minute != want_outward_min:
            continue
        journey_time_str = journey_time.strftime('%a %Y-%m-%d %H:%M')
        for fare in sorted(journey['fare'], key = lambda x: x['totalPrice']):
            if fare['fareClass'] != want_fare_class:
                continue
            if journey_time_str == prev_time_str:
                journey_time_str = '""""""""""""""""""""'
            else:
                prev_time_str = journey_time_str
            print('%s = £%.02f  %s' % (journey_time_str, int(fare['totalPrice'])/100.0, fare['description']))
        for bull in journey['serviceBulletins']:
            if not bull['cleared']:
                bull_desc = bull['description']
                if bull_desc not in bulletin:
                    bulletin += bull_desc + '. '
    for journey in resp['inwardJourney']:
        journey_time = journey['timetable']['scheduled']['departure']
        if journey_time.hour != want_inward_hour:
            continue
        journey_time_str = journey_time.strftime('%a %Y-%m-%d %H:%M')
        for fare in sorted(journey['fare'], key = lambda x: x['totalPrice']):
            if fare['fareClass'] != want_fare_class:
                continue
            if journey_time_str == prev_time_str:
                journey_time_str = '""""""""""""""""""""'
            else:
                prev_time_str = journey_time_str
            print('%s = £%.02f  %s' % (journey_time_str, int(fare['totalPrice'])/100.0, fare['description']))
        for bull in journey['serviceBulletins']:
            if not bull['cleared']:
                bull_desc = bull['description']
                if bull_desc not in bulletin:
                    bulletin += bull_desc + '. '
    print(bulletin)


def debug_request():
    node = client.create_message(client.service, 'RealtimeJourneyPlan',
        origin = { 'stationCRS': 'BYF' }, destination = { 'stationCRS': 'EDB' },
        realtimeEnquiry = 'STANDARD',
        outwardTime = { 'departBy': f'{tomorrow}T08:00:00' },
        directTrains = False
    )
    print('Message to be sent:')
    print (etree.tostring(node))#, pretty_print=True))


def send_request(client, tomorrow):
    """ Given a string in the form YYYY-MM-DD return the response dict
    which has been sanitised so it doesn't contain any XML. """

    response = client.service.RealtimeJourneyPlan(
        origin = { 'stationCRS': want_from }, destination = { 'stationCRS': want_to },
        realtimeEnquiry = 'STANDARD',
        outwardTime = { 'departBy': f'{tomorrow}T08:00:00' },
        inwardTime = { 'departBy': f'{tomorrow}T16:00:00' },
        fareRequestDetails = { 'passengers': { 'adult': 1, 'child': 0 }, 'fareClass': want_fare_class },
        directTrains = False,
        includeAdditionalInformation = False,
    )

    # Convert the response into a dict
    response_without_xml = serialize_object(response, dict)

    # Remove all dict keys called _raw_elements because they contain
    # raw XML which cannot be serialised to json or stored in a dill pickle
    remove_keys_recursively(response_without_xml, '_raw_elements')
    return response_without_xml


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description = 'OJP client')
    parser.add_argument('-d', '--debug', action='store_true', help='debug')
    parser.add_argument('-i', '--input', action='store', help='load an existing response for YYYY-MM-DD')
    parser.add_argument('-q', '--query', action='store', help='query for YYYY-MM-DD')
    args = parser.parse_args()
    if args.debug:
        debug = True

    tomorrow = datetime.date.today() + datetime.timedelta(days=1)
    tomorrow_str = tomorrow.strftime('%Y-%m-%d')

    if args.input:
        tomorrow_str = args.input
        resp = load_response_from_file(tomorrow_str)
        parse_response(resp)
    if args.query:
        tomorrow_str = args.query
        client = create_client(user, password)
        resp = send_request(client, tomorrow_str)
        parse_response(resp)
        save_response_to_file(tomorrow_str, resp)
