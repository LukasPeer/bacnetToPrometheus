#!/usr/bin/python3 -u

import os
import BAC0
import select
import sys
import json
from prometheus_client import CollectorRegistry, Gauge, generate_latest
import re
import http.server
import socketserver

# Read environment variables
local_address = os.getenv('LOCAL_ADDRESS', '0.0.0.0')
local_port = int(os.getenv('LOCAL_PORT', '47808'))
bbmd_address = os.getenv('BBMD_ADDRESS')
bbmd_ttl = int(os.getenv('BBMD_TTL', '300'))
bacnet_network = [int(n) for n in os.getenv('BACNET_NETWORK', '1').split(',')]
prometheus_port = 8000 # Can not be changed without changing the docker container itself

# Initialize the BAC0 lite server with the provided environment variables
bacnet = BAC0.lite(ip=local_address, port=local_port, bbmdAddress=bbmd_address, bbmdTTL=bbmd_ttl)

# Discover BACnet devices on the specified networks
devices = [BAC0.device(device[0], device[1], bacnet, history_size=10, poll=30) for device in bacnet.discover(networks=bacnet_network)]

# Check if any devices were found, raise an exception if none were found
if not devices:
    raise Exception('Could not find any devices')

# Function to sanitize metric names
def sanitize_metric_name(name):
    # Convert name to string and replace or remove invalid characters
    sanitized_name = re.sub(r'[^a-zA-Z0-9_]', '_', str(name))
    # Ensure the name starts with a letter or underscore
    return sanitized_name if sanitized_name[0].isalpha() or sanitized_name[0] == '_' else '_' + sanitized_name

# Function to handle list in metric names
def handle_list_for_metric_name(input_list):
    return '_'.join([sanitize_metric_name(item) for item in input_list])

# Initialize Prometheus metrics if a port is provided
if prometheus_port:
    registry = CollectorRegistry()
    gauges = {}

    def add_to_metrics(unit, value, documentation, device_name, point_name):
        # Check if value is None
        if value is None:
            return

        try:
            value = float(value)
        except ValueError:
            return

        if unit is None:
            unit = 'noUnit'
        elif isinstance(unit, list):
            # Handle list type units
            unit = handle_list_for_metric_name(unit)

        # Sanitize device_name and point_name before using them in metric name
        sanitized_device_name = sanitize_metric_name(device_name)
        sanitized_point_name = sanitize_metric_name(point_name)
        metric_name = f'bacnet_{sanitized_device_name}_{sanitized_point_name}_{unit}'

        if metric_name not in gauges:
            gauges[metric_name] = Gauge(metric_name, documentation, labelnames=['device', 'name'], registry=registry)
        
        gauges[metric_name].labels(device=sanitized_device_name, name=sanitized_point_name).set(value)

    for device in devices:
        device_name = device.properties.device_id
        for point in device.points:
            point_name = point.properties.name
            add_to_metrics(
                point.properties.units_state,
                point.lastValue,
                f'Present Value of BACnet objects with a {point.properties.units_state} unit',
                device_name,
                point_name
            )

    class MetricsHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain')
            self.end_headers()
            self.wfile.write(generate_latest(registry))

    httpd = socketserver.TCPServer(('', prometheus_port), MetricsHandler)
    print(f"Serving Prometheus metrics on port {prometheus_port}")
    httpd.serve_forever()

else:
    print("BAC0 exporter ready", file=sys.stderr)
