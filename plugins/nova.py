#!/usr/bin/env python

# (c) 2012, Marco Vito Moscaritolo <marco@agavee.com>
# (c) 2013, Jesse Keating <jesse.keating@rackspace.com>
# (c) 2014 Patrick "CaptTofu" Galbraith <patg@patg.net>
#
# This file is part of Ansible,
#
# Ansible is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Ansible is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Ansible.  If not, see <http://www.gnu.org/licenses/>.

import sys
import re
import os
import ConfigParser
import argparse
import collections
from novaclient.v1_1 import client as nova_client
from novaclient import exceptions
from types import NoneType

NOVA_CONFIG_FILES = [
    os.getcwd() + "/nova.ini",
    os.path.expanduser(
        os.environ.get(
            'ANSIBLE_CONFIG',
            "~/nova.ini")
    ),
    "/etc/ansible/nova.ini"
]

NON_CALLABLES = (basestring, bool, dict, int, list, NoneType)

try:
    import json
except:
    import simplejson as json


def nova_load_config_file(NOVA_DEFAULTS):
    p = ConfigParser.SafeConfigParser(NOVA_DEFAULTS)

    for path in NOVA_CONFIG_FILES:
        if os.path.exists(path):
            p.read(path)
            return p

    return None


def setup():
    # use a config file if it exists where expected
    NOVA_DEFAULTS = {
        'auth_system': 'keystone',
        'region_name': 'region1',
        'service_type': 'compute'
    }
    config = nova_load_config_file(NOVA_DEFAULTS)

    project_id = ""
    project_id = os.getenv('OS_TENANT_NAME')
    if project_id == '' or project_id is not None:
        project_id = os.getenv('OS_PROJECT_ID')

    nova_client_params = {
        'username': '',
        'password': '',
        'auth_url': 'https://127.0.0.1:35357/v2.0/',
        'project_id': '',
        'service_type': 'compute',
        'auth_system': 'keystone',
        'insecure': False,
    }
    if config is None:
        nova_client_params['username'] = os.getenv('OS_USERNAME')
        nova_client_params['password'] = os.getenv('OS_PASSWORD')
        nova_client_params['auth_url'] = os.getenv('OS_AUTH_URL')
        nova_client_params['region_name'] = os.getenv('OS_REGION_NAME')
        nova_client_params['project_id'] = os.getenv('OS_TENANT_NAME')
        nova_client_params['service_type'] = NOVA_DEFAULTS['service_type']
        nova_client_params['auth_system'] = NOVA_DEFAULTS['auth_system']
        nova_client_params['insecure'] = False
        if (nova_client_params['username'] == "" and
                nova_client_params['password'] == ""):
            sys.exit(
                'Unable to find config file in %s or environement variables'
                % ','
                .join(NOVA_CONFIG_FILES))
    else:
        nova_client_params['username'] = config.get('openstack', 'username')
        nova_client_params['password'] = config.get('openstack', 'password')
        nova_client_params['project_id'] = \
            config.get('openstack', 'project_id')
        nova_client_params['auth_url'] = config.get('openstack', 'auth_url')
        nova_client_params['region_name'] = \
            config.get('openstack', 'region_name')
        nova_client_params['service_type'] = \
            config.get('openstack', 'service_type')
        nova_client_params['auth_system'] = \
            config.get('openstack', 'auth_system')
        nova_client_params['insecure'] = config.get('openstack', 'insecure')

    nova_client_params['regions'] = \
        nova_client_params['region_name'].split(',')

    return(nova_client_params)


def to_dict(obj):
    instance = {}
    for key in dir(obj):
        value = getattr(obj, key)
        if (isinstance(value, NON_CALLABLES) and not key.startswith('_')):
            key = slugify('nova', key)
            instance[key] = value

    return instance


# TODO: this is something both various modules and plugins could use
def slugify(pre='', value=''):
    sep = ''
    if pre is not None and len(pre):
        sep = '_'
    return '%s%s%s' % (pre,
                       sep,
                       re.sub('[^\w-]', '_', value).lower().lstrip('_'))


def parse_args():
    parser = argparse.ArgumentParser(description='Nova Inventory Module')
    parser.add_argument('--private',
                        action='store_true',
                        help='Use private address for ansible host')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--list', action='store_true',
                       help='List active servers')
    group.add_argument('--host', help='List details about the specific host')
    return parser.parse_args()


def connect_to_nova(username='',
                    password='',
                    project_id='',
                    auth_url='',
                    region_name='',
                    service_type='',
                    auth_system='',
                    insecure=False):
    # Make the connection
    client = nova_client.Client(
        username,
        password,
        project_id,
        auth_url,
        region_name=region_name,
        service_type=service_type,
        auth_system=auth_system,
        insecure=insecure
    )

    try:
        client.authenticate()
    except exceptions.Unauthorized, e:
        print("Invalid OpenStack Nova credentials.: %s" %
              e.message)
        sys.exit(1)
    except exceptions.AuthorizationFailure, e:
        print("Unable to authorize user: %s" % e.message)
        sys.exit(1)

    if client is None:
        print("Failed to instantiate nova client. This "
              "could mean that your credentials are wrong.")
        sys.exit(1)

    return client


def host(nova_client_params, hostname, private_flag):
    hostvars = {}
    for region in nova_client_params['regions']:
        # Connect to the region
        client = connect_to_nova(nova_client_params['username'],
                                 nova_client_params['password'],
                                 nova_client_params['project_id'],
                                 nova_client_params['auth_url'],
                                 region,
                                 nova_client_params['service_type'],
                                 nova_client_params['auth_system'])
        for server in client.servers.list():
            # loop through the networks for this instance, append fixed
            # and floating IPs in a list
            private = [net['addr']
                       for net in
                       getattr(server, 'addresses').itervalues().next()
                       if 'OS-EXT-IPS:type'
                       in net and net['OS-EXT-IPS:type'] == 'fixed']
            public = [net['addr']
                      for net in
                      getattr(server, 'addresses').itervalues().next()
                      if 'OS-EXT-IPS:type'
                      in net and net['OS-EXT-IPS:type'] == 'floating']

            if server.name == hostname:
                for key, value in to_dict(server).items():
                    hostvars[key] = value

                # And finally, add an IP address
                if (private_flag is True):
                    hostvars[server.name]['ansible_ssh_host'] = private[0]
                else:
                    hostvars[server.name]['ansible_ssh_host'] = public[0]

    print(json.dumps(hostvars, sort_keys=True, indent=4))


def list_instances(nova_client_params, private_flag):
    groups = collections.defaultdict(list)
    hostvars = collections.defaultdict(dict)
    images = {}

    for region in nova_client_params['regions']:
        client = connect_to_nova(nova_client_params['username'],
                                 nova_client_params['password'],
                                 nova_client_params['project_id'],
                                 nova_client_params['auth_url'],
                                 region,
                                 nova_client_params['service_type'],
                                 nova_client_params['auth_system'])
        # Cycle on servers
        for server in client.servers.list():
            # loop through the networks for this instance, append fixed
            # and floating IPs in a list
            private = [net['addr']
                       for net in
                       getattr(server, 'addresses').itervalues().next()
                       if 'OS-EXT-IPS:type'
                       in net and net['OS-EXT-IPS:type'] == 'fixed']
            public = [net['addr']
                      for net in
                      getattr(server, 'addresses').itervalues().next()
                      if 'OS-EXT-IPS:type'
                      in net and net['OS-EXT-IPS:type'] == 'floating']

            # Create a group on region
            groups[region].append(server.name)

            # Check if group metadata key in servers' metadata
            group = server.metadata.get('group')
            if group:
                groups[group].append(server.name)

            for extra_group in server.metadata.get('groups', '').split(','):
                if extra_group:
                    groups[extra_group].append(server.name)

            for key, value in to_dict(server).items():
                hostvars[server.name][key] = value

            hostvars[server.name]['nova_region'] = region

            for key, value in server.metadata.iteritems():
                prefix = os.getenv('OS_META_PREFIX', 'meta')
                groups['%s_%s_%s' % (prefix, key, value)].append(server.name)

            if (private_flag is True):
                hostvars[server.name]['ansible_ssh_host'] = private[0]
            else:
                hostvars[server.name]['ansible_ssh_host'] = public[0]

            groups['instance-%s' % server.id].append(server.name)
            groups['flavor-%s' % server.flavor['id']].append(server.name)

            try:
                imagegroup = 'image-%s' % images[server.image['id']]
                groups[imagegroup].append(server.name)
                groups['image-%s' % server.image['id']].append(server.name)
            except KeyError:
                try:
                    image = client.images.get(server.image['id'])
                except client.exceptions.NotFound:
                    groups['image-%s' % server.image['id']].append(server.name)
                else:
                    images[image.id] = image.human_id
                    groups['image-%s' % image.human_id].append(server.name)
                    groups['image-%s' % server.image['id']].append(server.name)

            # And finally, add an IP address
            if (private_flag is True):
                hostvars[server.name]['ansible_ssh_host'] = private[0]
            else:
                hostvars[server.name]['ansible_ssh_host'] = public[0]

        if hostvars:
            groups['_meta'] = {'hostvars': hostvars}

    # Return server list
    print(json.dumps(groups, sort_keys=True, indent=2))
    sys.exit(0)


def main():
    args = parse_args()
    nova_client_params = setup()
    if args.list:
        list_instances(nova_client_params, args.private)
    elif args.host:
        host(nova_client_params, args.host, args.private)
    sys.exit(0)


if __name__ == '__main__':
    main()
