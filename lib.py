import json
import logging
import os
import subprocess
import time
from yaml import safe_load, YAMLError


def find_executable(executable, path=None):
    """Find the absolute path of an executable

    :return: path
    :rtype: str
    """
    _, ext = os.path.splitext(executable)

    if os.path.isfile(executable):
        return executable

    if path is None:
        path = os.environ.get("PATH", os.defpath)

    for p in path.split(os.pathsep):
        f = os.path.join(p, executable)
        if os.path.isfile(f):
            return f


def get_inventory():
    """Fetch ansible-inventory --list

    :return: inventory
    :rtype: dict
    """
    inventory_cmd = find_executable("ansible-inventory")
    if not inventory_cmd:
        raise Exception("Failed to identify path of ansible-inventory")

    inventory = None

    # read and invalidate the inventory cache file
    cache_file = os.environ.get("BASTION_ANSIBLE_INV_CACHE_FILE")
    if cache_file:
        cache = get_inventory_from_cache(
            cache_file=cache_file,
            cache_timeout=int(os.environ.get("BASTION_ANSIBLE_INV_CACHE_TIMEOUT", 60)),
        )
        if cache:
            inventory = cache.get("inventory")

    if inventory:
        return inventory

    # ex : export BASTION_ANSIBLE_INV_OPTIONS="-i my_inventory -i my_second_inventory"
    inventory_options = os.environ.get("BASTION_ANSIBLE_INV_OPTIONS", "")

    command = "{} {} --list".format(inventory_cmd, inventory_options)
    p = subprocess.Popen(
        command,
        shell=True,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    output, error = p.communicate()
    if type(output) is bytes:
        output = output.decode()
    if not p.returncode:
        inventory = json.loads(output)
        if cache_file:
            write_inventory_to_cache(cache_file=cache_file, inventory=inventory)
        return inventory
    else:
        logging.error(error)
        raise Exception("failed to query ansible-inventory")


def get_inventory_from_cache(cache_file, cache_timeout):
    """Read ansible-inventory from cache file

    :return: Inventory cache with `updated_at` (to expire the cache) and
        `inventory` (results of `ansible-inventory` command) keys.
    :rtype: dict
    """
    cache = None

    if os.path.isfile(cache_file):
        with open(cache_file, "r") as fd:
            cache = json.load(fd)
        # cache invalidation
        if cache.get("updated_at", 0) < int(time.time()) - cache_timeout:
            os.remove(cache_file)
            return None

    return cache


def write_inventory_to_cache(cache_file, inventory):
    """Write inventory with last update time to a cache file"""
    cache = {"inventory": inventory, "updated_at": int(time.time())}
    with open(cache_file, "w") as fd:
        json.dump(cache, fd)


def get_hostvars(host):
    """Fetch hostvars for the given host

    Ansible either uses the "ansible_host" inventory variable or the hostname.
    Fetch inventory and browse all hostvars to return only the ones for the host.

    :return: hostvars
    :rtype: dict
    """
    inventory = get_inventory()
    all_hostvars = inventory.get("_meta", {}).get("hostvars", {})
    for inventory_host, hostvars in all_hostvars.items():
        if inventory_host == host or hostvars.get("ansible_host") == host:
            return hostvars
    # Host not found
    return {}


def manage_conf_file(conf_file, bastion_host, bastion_port, bastion_user):
    """Fetch the bastion vars from a config file.
    
        There will be set if not already defined, and before looking in the ansible inventory
    
    """

    if os.path.exists(conf_file):
        try:
            with open(conf_file, "r") as f:
                yaml_conf = safe_load(f)

                if not bastion_host:
                    bastion_host = yaml_conf.get("bastion_host")
                if not bastion_port:
                    bastion_port = yaml_conf.get("bastion_port")
                if not bastion_user:
                    bastion_user = yaml_conf.get("bastion_user")

        except (YAMLError, IOError) as e:
            print("Error loading yaml file: {}".format(e))

    return bastion_host, bastion_port, bastion_user
