# rtjp

Real Time Journey Planner / client for the National Rail Online Journey Planner

This repo contains sample Python code which can query the web service to obtain all fares for a specific journey.

You need to register with National Rail for a username and password.

See https://www.nationalrail.co.uk/developers/online-journey-planner-data-feeds/

The sample code can query for a specific day and the output is saved in a python binary file.
This allows you to try different ways of extracting information from the response without
having to keep making queries that cost money.

The WSDL file which describes the service is also cached in a sqlite database as it's
unlikely to change and retrieving it every time would also incur a cost.

This example uses the Python Zeep library to make it easier to work with the SOAP and XML
https://docs.python-zeep.org/en/master/

## Usage

```
usage: rtjp.py [-h] [-d] [-i INPUT] [-q QUERY]

options:
  -h, --help            show this help message and exit
  -d, --debug           debug
  -i INPUT, --input INPUT
                        load an existing response for YYYY-MM-DD
  -q QUERY, --query QUERY
                        query for YYYY-MM-DD
```

Example: to run a query for 1 August 2024: `./rtjp.py -q 2024-08-01`
would display the results and also save them in a file `response_2024-08-01.dill`

Example: to re-run the query from the cache without making a web call:
`./rtjp.py -i 2024-08-01`

## Explanation of code

The first step is to open a connection to the web service,
download the WSDL if not already cached, and return the client object

Create a HTTP session with Basic authentication
```
    session = Session()
    session.auth = HTTPBasicAuth(user, password)
```

Determine the path to the WSDL cache
```
    cache = SqliteCache(path=cache_path, timeout=cache_life_seconds)
```

Create the transport using the HTTP session with the given cache
```
    transport = Transport(session=session, cache=cache)
```

Settings: turn off strict validation of XML otherwise it complains about missing items.
```
    settings = Settings(strict=False)
```

Open the client connection
```
    client = Client(wsdl_url, transport=transport, settings=settings)
```

The next step is to build a request, send it, and obtain the response.
We use the Python Zeep library to parse the WSDL and create functions
that we can call with a Python dictionary instead of manually constructing XML.

Assuming that we have variables containing the three-letter codes for the
origin and destination stations in `want_from` and `want_to`, and the date
as a `YYYY-MM-DD` string in `tomorrow`, and `want_fare_class` is `STANDARD`,
we can call the RealtimeJourneyPlan function:

```
    response = client.service.RealtimeJourneyPlan(
        origin = { 'stationCRS': want_from }, destination = { 'stationCRS': want_to },
        realtimeEnquiry = 'STANDARD',
        outwardTime = { 'departBy': f'{tomorrow}T08:00:00' },
        inwardTime = { 'departBy': f'{tomorrow}T16:00:00' },
        fareRequestDetails = { 'passengers': { 'adult': 1, 'child': 0 }, 'fareClass': want_fare_class },
        directTrains = False,
        includeAdditionalInformation = False,
    )
```

The Zeep helpers library can convert the response XML into a Python dict:
```
    response_without_xml = serialize_object(response, dict)
```

Unfortunately the response also contains elements called `_raw_elements`
which we don't want so we use a function that can remove any and all
instances of keys with that name from the dict:

```
    # Remove all dict keys called _raw_elements because they contain
    # raw XML which cannot be serialised to json or stored in a dill pickle
    remove_keys_recursively(response_without_xml, '_raw_elements')
```

The values we want are not in `response_without_xml`

In order to make use of the response we can parse it, let's get the departure time
for each train:
```
    for journey in resp['outwardJourney']:
        journey_time = journey['timetable']['scheduled']['departure']
```

Then we can get a list of fares for that train, sorted by totalPrice:
```
        for fare in sorted(journey['fare'], key = lambda x: x['totalPrice']):
```

You can do the same for the return train:
```
    for journey in resp['inwardJourney']:
```

There are also important announcements you might want to read:
```
        for bull in journey['serviceBulletins']:
            if not bull['cleared']:
                print(bull['description'])
```
