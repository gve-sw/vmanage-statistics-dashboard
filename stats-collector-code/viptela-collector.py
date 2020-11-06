#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Copyright (c) 2020 Cisco and/or its affiliates.
This software is licensed to you under the terms of the Cisco Sample
Code License, Version 1.1 (the "License"). You may obtain a copy of the
License at
               https://developer.cisco.com/docs/licenses
All use of the material herein must be in accordance with the terms of
the License. All rights not expressly granted by pytthe License are
reserved. Unless required by applicable law or agreed to separately in
writing, software distributed under the License is distributed on an "AS
IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express
or implied.
"""


__author__ = "Eduard Schornig <eschorni@cisco.com>"
__contributors__ = [
    "Josh Ingeniero <jingenie@cisco.com>"
]
__copyright__ = "Copyright (c) 2020 Cisco and/or its affiliates."
__license__ = "Cisco Sample Code License, Version 1.1"

from API_Utils import ViptelaRestApiLib as ViRAL
from pprint import pprint as pp
import logging
import sys

import yaml
import json
from influxdb import InfluxDBClient
from datetime import datetime, timedelta, timezone
from timeloop import Timeloop
from time import sleep, time

import urllib3
urllib3.disable_warnings()

__author__  = "Eduard Schornig (eschorni@cisco.com)"
__version   = 0.3

logging.addLevelName(25, '__INFO__')
logging.basicConfig(stream=sys.stdout,
                    format='%(asctime)s: %(module)s [%(funcName)20s] [%(process)s] [%(levelname)s]: %(message)s',
                    datefmt='%m/%d/%Y %H:%M:%S')

global info


class vManageStatsCollector(object):
    def __init__(self, config=None):
        self.vM_ip = config['ip']
        self.vM_user = config['user']
        self.vM_pass = config['pass']
        self.vM_desc = config['desc']
        logging.log(25, 'Initializing vManage API Object for: {} @ {}'.format(self.vM_desc, self.vM_ip))


    def Connect(self):
        self.vManageSession = ViRAL(self.vM_ip, 
                                    self.vM_user,
                                    self.vM_pass)
    
        logging.log(25, 'Opening API Session for to vManage: {} @ {}'.format(self.vM_desc, self.vM_ip))

    def SLAChange(self, query_data=None):
        global info
        payload = {
            "query": {
                "condition": "AND",
                "rules": [
                    {
                        "value": [
                            "24"
                        ],
                        "field": "entry_time",
                        "type": "date",
                        "operator": "last_n_hours"
                    },
                    {
                        "value": [
                            "sla-change",
                            "sla-violation",
                            "sla-violation-pkt-drop"
                        ],
                        "field": "eventname",
                        "type": "string",
                        "operator": "in"
                    }
                ]
            }
        }

        data = self.vManageSession.post_request(query_data['url_endpoint'], payload=payload)
        # pp(data)
        logging.log(25, 'Run API Call: {}.'.format(query_data['url_endpoint']))

        dataInflux = list()

        for entry in data['data']:

            tags, fields = dict(), dict()
            tags['host'] = self.vM_ip
            tags['region'] = self.vM_desc

            details = dict()

            # Parsing the details of the sla entry

            mixedInfo = entry["details"]
            infos = mixedInfo.replace(" ", "")
            infos = infos.split(";")
            for line in infos:
                stuff = line.split("=")
                # For sla-information which has an interesting format
                if stuff[0] == "sla-information":
                    details['Loss'] = stuff[3].split("%")[0]
                    details['Latency'] = stuff[4].split("ms")[0]
                    details['Jitter'] = stuff[5].split("ms")[0]
                    continue
                # For everything else
                details[stuff[0]] = stuff[1]

            for tag in query_data['tags']:
                try:
                    tags[tag] = details[tag]
                except:
                    pass

            for field in query_data['fields']:
                try:
                    if "mean" in field or "Loss" in field or "Latency" in field or "Jitter" in field:
                        fields[field] = int(details[field])
                    else:
                        fields[field] = details[field]
                except:
                    pass

            measurement = {'measurement': query_data['series_name'],
                           'tags': tags,
                           'time': datetime.fromtimestamp(entry['entry_time']/1000, tz=timezone.utc),
                           'fields': fields
                           }

            # Only update if we have valid data points
            if fields:
                dataInflux.append(measurement)

        return dataInflux

    def SimpleAPICall(self, query_data=None):

        data = self.vManageSession.get_request(query_data['url_endpoint'])

        logging.log(25, 'Run API Call: {}.'.format(query_data['url_endpoint']))

        dataInflux = list()

        for entry in data['data']:
            tags, fields = dict(), dict()

            tags['host'] = self.vM_ip
            tags['region'] = self.vM_desc
            for tag in query_data['tags']:
                if tag in entry:
                    tags[tag.replace('-', '_')] = entry[tag]

            for field in query_data['fields']:
                if field in entry and entry[field] != '--':
                    fields[field] = setType(field, entry[field], data['header']['fields'])

            measurement = {'measurement': query_data['series_name'],
                           'tags': tags,
                           'time': datetime.now(timezone.utc),
                           'fields': fields
                           }

            # Only update if we have valid data points
            if fields:
                dataInflux.append(measurement)

        return dataInflux

    def AggregateAPICall(self, query_data=None):
        global info

        payload = {'query': {'condition': 'AND',
                             'rules': [{
                                 'field': 'entry_time',
                                 'operator': 'between',
                                 'type': 'date',
                                 'value': [
                                     '{} UTC'.format((datetime.utcnow() - timedelta(minutes=query_data['stats_interval'])).strftime('%Y-%m-%dT%H:%M:%S')),
                                     '{} UTC'.format(datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S'))
                                 ]}]}}

        data = self.vManageSession.post_request(query_data['url_endpoint'], payload=payload)
        # pp(data)
        logging.log(25, 'Run API Call: {}.'.format(query_data['url_endpoint']))

        dataInflux = list()

        if query_data['url_endpoint'] == 'statistics/approute':
            info = list()

        for entry in data['data']:

            tags, fields = dict(), dict()
            tags['host'] = self.vM_ip
            tags['region'] = self.vM_desc

            for tag in query_data['tags']:
                if tag in entry:
                    tags[tag] = entry[tag]
                else:
                    # Need to fix this.
                    tags[tag] = '--'

            for field in query_data['fields']:
                if field in entry and entry[field] != '--':
                    fields[field] = setType(field, entry[field], data['header']['fields'])

            # Append AAR to DPI information
            if query_data['url_endpoint'] == 'statistics/dpi':
                SECTIME = query_data['variation_interval']
                for item in info:
                    if item['tags']['host_name'] == entry['host_name']:
                        if item['tags']['tunnel_color'] == f"{entry['local_color']}:{entry['remote_color']}":
                            if item['tags']['remote_system_ip'] == entry['remote_system_ip']:
                                if int(item['tags']['entry_time']) in range(int(entry['entry_time'])-SECTIME*1000,
                                                                             int(entry['entry_time'])+SECTIME*1000):
                                    fields['Loss'] = item['fields']['loss_percentage']
                                    fields['Latency'] = item['fields']['latency']
                                    fields['Jitter'] = item['fields']['jitter']

            measurement = {'measurement': query_data['series_name'],
                           'tags': tags,
                           'time': datetime.fromtimestamp(entry['entry_time']/1000, tz=timezone.utc),
                           'fields': fields
                           }

            # Only update if we have valid data points
            if fields:
                dataInflux.append(measurement)

            if query_data['url_endpoint'] == 'statistics/approute':
                info.append(measurement)

        return dataInflux

    def BulkAPICall(self, query_data=None):

        query_start_date = '{}'.format((datetime.utcnow() - timedelta(minutes=query_data['stats_interval'])).strftime('%Y-%m-%dT%H:%M:%S'))
        query_end_date = '{}'.format(datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S'))

        url = '{api_endpoint}?startDate={start}&endDate={end}&timeZone=UTC'.format(api_endpoint=query_data['url_endpoint'],
                                                                                   start=query_start_date,
                                                                                   end=query_end_date)

        data = self.vManageSession.get_request(url)

        logging.log(25, 'Run API Call: {} @ last {} min.'.format(query_data['url_endpoint'],
                                                                 query_data['stats_interval']))

        dataInflux = list()

        for entry in data['data']:
            tags, fields = dict(), dict()
            tags['host'] = self.vM_ip
            tags['region'] = self.vM_desc

            for tag in query_data['tags']:
                tags[tag.replace('-', '_')] = entry[tag]

            for field in query_data['fields']:
                if field in entry and entry[field] != '--':
                    fields[field] = setType(field, entry[field], data['header']['fields'])

            measurement = {'measurement': query_data['series_name'],
                           'tags': tags,
                           'time': datetime.fromtimestamp(entry['entry_time']/1000, tz=timezone.utc),
                           'fields': fields
                           }

            # Only update if we have valid data points
            if fields:
                dataInflux.append(measurement)

        return dataInflux


class influxAgent(object):
    def __init__(self, config=None):
        self.db_ip = config['db_ip']
        self.db_port = config['db_port']
        self.db_name = config['db_name']
        self.db_user = config['db_user']
        self.db_pass = config['db_pass']
        logging.log(25, 'Initializing InfluxDB API Object for: {} @ {}'.format(self.db_ip, self.db_name))

    def Connect(self, clean=False):
        self.client = InfluxDBClient(self.db_ip,
                                     self.db_port,
                                     self.db_user,
                                     self.db_pass,
                                     self.db_name)

        logging.log(25, 'Opening DB Socket for: {} @ {}'.format(self.db_ip, self.db_name))

        if clean:
            self.client.drop_database(self.db_name)
            logging.log(25, 'Clean flag set, dropping DB {} on {}.'.format(self.db_name, self.db_ip))


        self.client.create_database(self.db_name)

    def Update(self, data):
        #pp(data)
        self.client.write_points(data)
        logging.log(25, 'Updated DB with {} datapoints.'.format(len(data)))


def setType(field_name, field_data, field_map):

    field_type = [entry['dataType'] for entry in field_map if entry['property'] == field_name]

    if field_type:
        field_type = field_type.pop()
        try:
            if '(' in field_data and field_type == 'numberStr':
                field_data =field_data.split(' (')[0]
        except TypeError:
            pass

        if field_type == 'numberStr' or field_type == 'double':
            return float(field_data)
        elif field_type == 'number':
            return int(field_data)
        else:
            return field_data

    # Not all fields have a dataType entry
    elif '_avg' in field_name:
        return float(field_data)
    elif 'ompPeers' in field_name:
        try:
            if '(' in field_data:
                field_data =field_data.split(' (')[0]
        except TypeError:
            pass
        return int(field_data)
    else:
        return field_data


def TaskScheduller(vm=None, db=None, measurements=None):
    tsort_measurements = dict()

    for entry in measurements:
        collect_interval = measurements[entry]['collect_interval']
        if collect_interval not in tsort_measurements:
            tsort_measurements[collect_interval] = list()
        tsort_measurements[collect_interval].append(measurements[entry])

    for collect_interval, measurements_list in tsort_measurements.items():
        current_time_sec = int(time())
        if current_time_sec % collect_interval == 0:
            #vm.Connect()
            #db.Connect()
            data_points = list()
            logging.log(25, 'Collection loop interval={} seconds @ {}'.format(collect_interval, datetime.now()))
            for entry in measurements_list:
                query_data = entry['query_data']
                query_type = entry['query_type']

                data_points += getattr(vm, query_type)(query_data=query_data)
            
            db.Update(data_points)


def main():
    print("Test")
    config_file = 'credentials.yaml'
    with open(config_file, 'r') as f:
        config = yaml.safe_load(f)
    
    # Wait 60 seconds after container started before trying to initiate connections to vManage or InfluxDB
    # Also protecs agaings spamming vManage and vSmart with connection requests should we have a problem with stats processing.
    sleep(60)

    influx_db = influxAgent(config=config['influxdb'])
    influx_db.Connect()
    #influx_db.Connect(clean=True)
    vManage_API = vManageStatsCollector(config=config['vManage'])
    vManage_API.Connect()

    def Periodic_1s():
        # Update measurement list
        config_file = 'measurements.yaml'
        with open(config_file, 'r') as f:
            config = yaml.safe_load(f)

        # Run API Calls

        TaskScheduller(vm=vManage_API, db=influx_db, measurements=config['Measurements'])

    while True:
        # Periodic loop to check if we need to run any measurements
        Periodic_1s()
        sleep(1)

if __name__ == '__main__':
    main()
