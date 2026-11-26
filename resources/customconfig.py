#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os
import socket
import json
from pprint import pprint, pformat
import logging
from pathlib import Path
from base64 import b64decode, b64encode
from contextlib import asynccontextmanager
import traceback
import textwrap
import sys
import subprocess
import traceback

from oauthenticator.oauth2 import OAuthenticator
from oauthenticator.generic import GenericOAuthenticator
from oauthenticator.google import GoogleOAuthenticator
from tornado import gen
from tornado.web import HTTPError
from tornado.concurrent import run_on_executor
from kubespawner import KubeSpawner
import requests
from requests.auth import HTTPBasicAuth
import yaml
import subprocess
import warnings
import asyncio
import shutil
import copy
import string
import re
import time
from collections import defaultdict

from typing import Dict, Collection, Literal

import jinja2
import kubernetes_asyncio as k8s
from kubernetes_asyncio.client.models import (
    V1Service,
    V1ObjectMeta,
    V1ServiceSpec,
    V1ServicePort,
)


################################################################################
## Configurable environment

################################################################################
## Authentication
AUTHENTICATOR = os.environ.get("AUTHENTICATOR", "IAM")
if AUTHENTICATOR not in ["IAM", "GOOGLE"]:
    raise Exception(
        f"Unsupported authenticator {AUTHENTICATOR}. Supported values are: IAM, GOOGLE."
    )

# Used by both GOOGLE and IAM authenticators
IAM_CLIENT_ID = os.environ["IAM_CLIENT_ID"]
IAM_CLIENT_SECRET = os.environ["IAM_CLIENT_SECRET"]

# Only relevant for GOOGLE authenticator
ALLOWED_GOOGLE_DOMAINS = json.loads(
    os.environ.get("ALLOWED_GOOGLE_DOMAINS", '["unifi.it", "edu.unifi.it"]')
)
ALLOWED_GOOGLE_USERS = json.loads(os.environ.get("ALLOWED_GOOGLE_USERS", "[]"))
ADMIN_GOOGLE_USERS = json.loads(os.environ.get("ADMIN_GOOGLE_USERS", "[]"))

BANNED_GOOGLE_USERS = json.loads(os.environ.get("BANNED_GOOGLE_USERS", "[]"))

# Only relevant for IAM authenticator
OAUTH_CALLBACK_URL = os.environ.get("OAUTH_CALLBACK_URL")
OAUTH_ENDPOINT = os.environ.get("OAUTH_ENDPOINT")
OAUTH_GROUPS = os.environ.get("OAUTH_GROUPS")
OAUTH_ADMIN_GROUPS = os.environ.get("OAUTH_ADMIN_GROUPS")

if AUTHENTICATOR == "IAM" and OAUTH_CALLBACK_URL is None:
    raise Exception(
        "OAUTH_CALLBACK_URL Oenvironment variables must be set when using IAM authenticator."
    )
if AUTHENTICATOR == "IAM" and OAUTH_ENDPOINT is None:
    raise Exception(
        "OAUTH_ENDPOINT Oenvironment variables must be set when using IAM authenticator."
    )
if AUTHENTICATOR == "IAM" and OAUTH_GROUPS is None:
    raise Exception(
        "OAUTH_GROUPS Oenvironment variables must be set when using IAM authenticator."
    )
if AUTHENTICATOR == "IAM" and OAUTH_ADMIN_GROUPS is None:
    raise Exception(
        "OAUTH_GROUPS Oenvironment variables must be set when using IAM authenticator."
    )


################################################################################
## File system
START_TIMEOUT = int(os.environ.get("START_TIMEOUT", 20))
NFS_MOUNT_POINT = Path(os.environ.get("NFS_MOUNT_POINT", "/nfs-shared"))
NFS_SERVER_ADDRESS = os.environ.get("NFS_SERVER_ADDRESS")
NFS_SERVER_HTTP_PORT = int(os.environ.get("NFS_SERVER_HTTP_PORT", "3000"))
NFS_SERVER_HTTP_TLS = os.environ.get("NFS_SERVER_HTTP_TLS", "no") in [
    "true",
    "yes",
    "y",
]
NFS_SERVER_ADMIN_USER = os.environ.get("NFS_SERVER_ADMIN_USER", "filesystem-admin")
NFS_SERVER_ADMIN_PASSWORD = os.environ.get("NFS_SERVER_ADMIN_PASSWORD", "pincopanco")

JUICEFS_ENABLED = os.environ.get("JUICEFS_ENABLED") in ["true", "yes", "y"]
JUICEFS_MOUNT_POINT = Path(os.environ.get("JUICEFS_MOUNT_POINT", "/jfs"))
JUICEFS_PVC_NAME = os.environ.get("JUICEFS_PVC_NAME", "juicefs")
JUICEFS_S3_BUCKET = os.environ.get("JUICEFS_S3_BUCKET", "")
JUICEFS_S3_ACCESS_KEY = os.environ.get("JUICEFS_S3_ACCESS_KEY", "")
JUICEFS_S3_SECRET_KEY = os.environ.get("JUICEFS_S3_SECRET_KEY", "")
JUICEFS_METADATA_DB = os.environ.get("JUICEFS_METADATA_DB", "")
JUICEFS_FILESYSTEM_NAME = os.environ.get("JUICEFS_FILESYSTEM_NAME", "")
CVMFS_CLAIM_NAME = os.environ.get("CVMFS_CLAIM_NAME", "")

# Host path volume mounted only in sessions spawned with an FPGA
FPGA_INPUT_DATA_VOLUME = "fpga-input-data"
FPGA_INPUT_DATA_HOST_PATH = os.environ.get(
    "FPGA_INPUT_DATA_HOST_PATH", "/data/input_data/AI_INFN"
)
FPGA_INPUT_DATA_MOUNT_PATH = os.environ.get(
    "FPGA_INPUT_DATA_MOUNT_PATH", "/data/AI_INFN"
)

PRIVILEGED_USERS = os.environ.get("PRIVILEGED_USERS", "no") in ["true", "yes", "y"]

STARTUP_SCRIPT = Path(os.environ.get("STARTUP_SCRIPT", "/envs/setup.sh"))
DEBUG = os.environ.get("DEBUG", "").lower() in ["true", "yes", "y"]
HOME_NAME = os.environ.get("HOME_NAME", "home")
SSH_PORT = int(os.environ.get("SSH_PORT", 22))
JHUB_NAMESPACE = os.environ.get("JHUB_NAMESPACE", "default")
NFS_VOLUME_PREFIX = os.environ.get("NFS_VOLUME_PREFIX", JHUB_NAMESPACE)
DEFAULT_SPLASH_MESSAGE = os.environ.get("DEFAULT_SPLASH_MESSAGE", "Welcome")
DEFAULT_JLAB_IMAGES = json.loads(
    os.environ.get(
        "DEFAULT_JLAB_IMAGES",
        '{"Default image": "harbor.cloud.infn.it/testbed-dm/ai-infn:0.1-pre10"}',
    )
)
FPGA_FORCED_IMAGE = os.environ.get(
    "FPGA_FORCED_IMAGE", "quay.io/fpgacourse2025/hackathon2026:0.0.9"
)
ALLOW_HOST_PATHS_ON_REMOTE = os.environ.get(
    "ALLOW_HOST_PATHS_ON_REMOTE", ""
).lower() in ["true", "yes", "y"]

GPU_MODEL_DESCRIPTION = json.loads(os.environ.get("GPU_MODEL_DESCRIPTION", "[]"))
DCGM_EXPORTER_NAMESPACE = os.environ.get("DCGM_EXPORTER_NAMESPACE", "gpu-operator")
DCGM_EXPORTER_LABEL = "app=nvidia-dcgm-exporter"
DCGM_METRICS_PORT = 9400
LABELS_RE = re.compile(r"\{([^}]*)\}\s+([-+eE0-9.]+)")
SPLIT_RE = re.compile(r'(\w+)=(".*?"|[^,]+)')
CONFIGMAP_MOUNT_PATH = Path(
    os.environ.get(
        "CONFIGMAP_MOUNT_PATH",
        os.path.join(os.path.dirname(__file__), "jupyterhub_config.d"),
    )
)

# Metrics custom token
METRICS_API_KEY = os.environ.get("JUPYTERHUB_METRICS_API_KEY")


# Virtual Kubelet Dispatcher configuration
ENABLE_VKD = os.environ.get("ENABLE_VKD", "").lower() in ["true", "yes", "y"]
VKD_SIDECAR_IMAGE = os.environ.get(
    "VKD_SIDECAR_IMAGE", "harbor.cloud.infn.it/testbed-dm/vkd-dev:v0.0"
)
VKD_SIDECAR_NAME = os.environ.get("VKD_SIDECAR_NAME", "vkd")
VKD_SIDECAR_PULLPOLICY = os.environ.get("VKD_SIDECAR_PULLPOLICY", "IfNotPresent")
VKD_ADMIN_SERVICE_ACCOUNT = os.environ.get("VKD_ADMIN_SERVICE_ACCOUNT", "vkd-admin")
VKD_USER_SERVICE_ACCOUNT = os.environ.get("VKD_USER_SERVICE_ACCOUNT", "vkd-user")
VKD_ADMIN_USER_GROUP = os.environ.get("VKD_ADMIN_USER_GROUP", "vkd")
VKD_PORT = os.environ.get("VKD_PORT", "8000")
VKD_IMAGE_BRANCH = os.environ.get("VKD_IMAGE_BRANCH", "main")
VKD_NAMESPACE = os.environ.get("VKD_NAMESPACE", "vkd")


SYSTEM_VOLUMES = json.loads(os.environ.get("SYSTEM_VOLUMES", '["www", "vkd"]'))

# Resources
AVAILABLE_CPU = json.loads(os.environ.get("AVAILABLE_CPU", "[1, 2]"))
AVAILABLE_MEMORY_GB = json.loads(os.environ.get("AVAILABLE_MEMORY_GB", "[4, 8]"))
EXTENDED_RESOURCES = json.loads(
    os.environ.get("EXTENDED_RESOURCES", '["ai.infn.it/fuse"]')
)

## Slurm
SLURM_CONF_SERVER = os.environ.get("SLURM_CONF_SERVER", "slurm-controller.slurm:6817")


if "JUPYTERHUB_CRYPT_KEY" not in os.environ.keys():
    raise Exception(
        "Environment variable JUPYTERHUB_CRYPT_KEY not set: run `openssl rand -hex 32` to generate."
    )

log_format = "%(asctime)-22s %(levelname)-8s %(message)-90s"
logging.basicConfig(
    format=log_format,
    level=logging.DEBUG if DEBUG else logging.INFO,
)

logging.info(
    "Starting custom INFN configuration of JupyterHub Spawner (from ConfigMap)"
)
for global_var in list(globals().keys()):
    if global_var.upper() == global_var:
        logging.info(
            f"{global_var.replace('_', ' ') + ':':<30s} {pformat(globals().get(global_var))}"
        )
logging.info("=" * 16)


################################################################################
## Direct access to kubernetes APIs

k8s.config.load_incluster_config()


@asynccontextmanager
async def kubernetes_api(group: str = "core"):
    _API_GROUPS_ = dict(
        core=k8s.client.CoreV1Api, custom_object=k8s.client.CustomObjectsApi
    )

    try:
        yield _API_GROUPS_[group]()
    except k8s.client.exceptions.ApiException as exception:
        try:
            body = json.loads(exception.body)
        except json.JSONDecodeError:
            logging.error("HTTP error not returning a JSON.")
            logging.error(traceback.print_exc())
            raise Exception(f"{exception.status} ({exception.reason}) {exception.body}")
        else:
            logging.error(f"Error {exception.status} ({exception.reason})")
            message = body.get("message", "Kubernetes error")
            logging.error(message)
            logging.error(traceback.print_exc())
            raise Exception(message)
    except Exception as e:
        logging.error(str(e))
        logging.error(traceback.print_exc())
        raise Exception("Unknown kubernetes error")


def setup_nfs_user(spawner):
    """Access the management layer of NFS server via HTTPS and setup the user"""
    username = spawner.get_user_name()
    project_groups = spawner.get_user_groups()
    logging.info(
        f"Setting up NFS user for {username} with groups {project_groups} and tenancy {NFS_VOLUME_PREFIX}"
    )
    nfs_user_response = requests.get(
        f"http{'s' if NFS_SERVER_HTTP_TLS else ''}://{NFS_SERVER_ADDRESS}:{NFS_SERVER_HTTP_PORT}/ensure-user",
        params=dict(
            name=username, groups="+".join(project_groups), tenancy=NFS_VOLUME_PREFIX
        ),
        auth=HTTPBasicAuth(NFS_SERVER_ADMIN_USER, NFS_SERVER_ADMIN_PASSWORD),
    )

    if nfs_user_response.status_code != 200:
        return (
            507,
            f"Failed while trying to ensure directories for user's home and groups. {nfs_user_response.text}",
        )

    try:
        nfs_user_data = nfs_user_response.json()

        spawner.environment["NB_USER"] = nfs_user_data["username"]
        spawner.environment["NB_UID"] = nfs_user_data["uid"]
        spawner.environment["NB_GID"] = nfs_user_data["gid"]
        spawner.environment["NB_GROUP"] = nfs_user_data["groupname"]
        spawner.environment["JUPYTER_SERVER_ROOT"] = f"/{HOME_NAME}"
        spawner.environment["GRANT_SUDO"] = (
            "1" if spawner.check_privilege("sudoer") else "0"
        )
        spawner.environment["NB_GROUPS"] = ", ".join(
            [f"{g['gid']}:{g['name']}" for g in nfs_user_data["groups"]]
        )
        return (200, nfs_user_data)
    except ValueError:
        return (500, "Invalid response from NFS server")


def setup_slurm_environment(spawner):
    logging.info(
        f"Setting up SLURM environment for user {spawner.get_user_name()}. Server: {SLURM_CONF_SERVER}"
    )
    spawner.environment.update(
        dict(
            SACKD_ARGS="--conf-server " + SLURM_CONF_SERVER,
        )
    )


class ConfigurableGoogleAuthenticator(GoogleOAuthenticator):
    """
    Configurable GoogleOAuthenticator specialized for Gmail-provided identities.
    """

    async def authenticate(self, handler, data=None):
        auth_model = await GenericOAuthenticator.authenticate(self, handler, data)
        pprint("User info:")
        user_info = auth_model["auth_state"][self.user_auth_state_key]
        pprint(user_info)

        print("Enabled auth_state:", self.enable_auth_state)

        domain = user_info.get("domain")
        email = user_info.get("email")
        user_admin = email in ADMIN_GOOGLE_USERS
        user_banned = email in BANNED_GOOGLE_USERS
        user_allowed = (not user_banned) and (
            user_admin
            or (email in ALLOWED_GOOGLE_USERS)
            or (domain in ALLOWED_GOOGLE_DOMAINS)
        )

        if user_banned:
            error_msg = f"Your email '{email}' is not banned. Get in touch with the administrator if you think this is a mistake."
            self.log.error(error_msg)
            raise HTTPError(403, error_msg)

        if not user_allowed:
            error_msg = (
                f"This service is reserved. Your email '{email}' is not allowed."
            )
            self.log.error(error_msg)
            raise HTTPError(403, error_msg)

        auth_model["admin"] = user_admin

        return auth_model

    async def pre_spawn_start(self, user, spawner):
        """
        Function called during the spawning process to:
         * make sure the user is still authenticated and belongs to the right groups
         * copy (some) of the authentication tokens to the spawned single-user server as env var

        """
        self.log.info(f"Pre spawn start for user {str(user)}")
        auth_state = await user.get_auth_state()
        if not auth_state:
            # user has no auth state
            warnings.warn("Could not retrieve user's auth_state at spawning")
            return

        user_info = auth_state[self.user_auth_state_key]

        domain = user_info.get("domain")
        email = user_info.get("email")
        user_admin = email in ADMIN_GOOGLE_USERS
        user_allowed = (
            (domain in ALLOWED_GOOGLE_DOMAINS)
            or (email in ALLOWED_GOOGLE_USERS)
            or user_admin
        )

        if not user_allowed:
            error_msg = f"User email '{email}' is not member of any of the allowed domains: {','.join(ALLOWED_GOOGLE_DOMAINS)}"
            self.log.error(error_msg)
            self.throw_http(403, error_msg)

        # Setup the user on the NFS server
        setup_res = setup_nfs_user(spawner)
        if setup_res[0] != 200:
            self.throw_http(*setup_res)

        if spawner.check_privilege("slurm"):
            setup_slurm_environment(spawner)

    def user_info_to_username(self, user_info):
        username = super().user_info_to_username(user_info)

        pprint(f"Parsing username: {username}")
        pprint(user_info)
        username, domain = username.split("@")
        return "".join(
            (letter for letter in username.lower() if letter in string.ascii_lowercase)
        )

    def throw_http(self, status_code: int, error_msg: str):
        self.log.error(error_msg)
        self.log.error(traceback.print_exc())

        exc = HTTPError(status_code, error_msg, headers={})
        exc.headers = {}
        raise exc


################################################################################
## IAM Authenticator


class IamAuthenticator(GenericOAuthenticator):
    """
    Custom implementation of the OAuth2 authenticator.
    """

    async def update_auth_model(self, auth_model):
        print("update_auth_model", pformat(auth_model))
        groups = auth_model["auth_state"].get("oauth_user", {}).get("groups", [])
        auth_model["auth_state"]["oauth_user"] = auth_model["auth_state"].get(
            "oauth_user", {}
        )
        auth_model["auth_state"]["oauth_user"]["scopes"] = auth_model.get("scopes", [])
        username = auth_model["name"]
        # username = auth_model["auth_state"]["oauth_user"].get("preferred_username", "User with no name")

        user_allowed = any([g in OAUTH_GROUPS.split(" ") for g in groups])
        auth_model["admin"] = any([g in OAUTH_ADMIN_GROUPS.split(" ") for g in groups])

        if auth_model["admin"]:
            logging.info(f"{username} is authorized as ADMIN")
        if user_allowed:
            self.allowed_users.add(username)
            logging.info(f"{username} is authorized")
        else:
            auth_model["auth_state"]["oauth_user"]["scopes"] = []
            logging.warning(f"{username} is NOT authorized")

        return auth_model

    def throw_http(self, status_code: int, error_msg: str):
        self.log.error(error_msg)
        self.log.error(traceback.print_exc())

        exc = HTTPError(status_code, error_msg, headers={})
        exc.headers = {}
        raise exc

    async def pre_spawn_start(self, user, spawner):
        """
        Function called during the spawning process to:
         * make sure the user is still authenticated and belongs to the right groups
         * copy (some) of the authentication tokens to the spawned single-user server as env var

        """
        auth_state = await user.get_auth_state()
        if not auth_state:
            # user has no auth state
            warnings.warn("Could not retrieve user's auth_state at spawning")
            return

        username = auth_state["oauth_user"]["preferred_username"]
        project_groups = spawner.get_user_groups()
        print(f"project groups: {project_groups}")

        # Setup the user on the NFS server
        setup_res = setup_nfs_user(spawner)
        if setup_res[0] != 200:
            self.throw_http(*setup_res)

        if spawner.check_privilege("slurm"):
            setup_slurm_environment(spawner)

        # define some environment variables from auth_state
        self.log.info(auth_state)
        spawner.environment["IAM_SERVER"] = OAUTH_ENDPOINT
        spawner.environment["IAM_CLIENT_ID"] = IAM_CLIENT_ID
        spawner.environment["IAM_CLIENT_SECRET"] = IAM_CLIENT_SECRET
        spawner.environment["ACCESS_TOKEN"] = auth_state["access_token"]
        spawner.environment["REFRESH_TOKEN"] = auth_state["refresh_token"]
        spawner.environment["USERNAME"] = auth_state["oauth_user"]["preferred_username"]
        spawner.environment["JUPYTERHUB_ACTIVITY_INTERVAL"] = "15"

        user_info = auth_state[self.user_auth_state_key]
        iam_groups = auth_state.get("oauth_user", {}).get("groups")

        allowed_groups = os.environ.get("OAUTH_GROUPS", "").split(" ")
        user_allowed = any([g in allowed_groups for g in iam_groups])

        if not user_allowed:
            self.throw_http(
                403,
                f"User is not member of any of the allowed groups: {','.join(allowed_groups)}",
            )

    # async def authenticate(self, handler, data=None):
    #   auth_model = await GenericOAuthenticator.authenticate(self, handler, data)
    #   pprint ("User info:")
    #   user_info = auth_model["auth_state"][self.user_auth_state_key]
    #   pprint(user_info)
    #   pprint ("Groups:")
    #   pprint (self.get_user_groups(user_info))

    #   return auth_model


################################################################################
## SplashManager


## Try to install markdown optional dependency


class SplashManager:
    def __init__(self, resource):
        self._resource = resource

    @property
    def resource(self):
        return self._resource

    def message(self, **kwargs):
        if os.path.exists(self.resource):
            with open(self.resource) as splash_file:
                template = splash_file.read()
        else:
            template = textwrap.dedent(f"""
              <h3>{DEFAULT_SPLASH_MESSAGE}</h3>
              <P>You are logged as: {{{{ username }}}}</P>
              <P>You are member of the following projects: {{{{ groups | join(", ") }}}} </P>
            """)
            with open(self.resource, "w") as splash_file:
                splash_file.write(template)

        return jinja2.Template(template).render(**kwargs)


################################################################################
## Helper static functions
def _prefer_accelerator(node_selectors: Dict[str, str], weight=1):
    """
    Internal. Format the preference for an accelerator as an nodeAffinity preference.
    """
    return dict(
        weight=weight,
        preference=dict(
            matchExpressions=[
                {"key": label, "operator": "In", "values": [value]}
                for label, value in node_selectors.items()
            ]
        ),
    )


def _node_matches(node, node_selectors: Dict[str, str]):
    """
    Internal. True if the node carries all the (non-empty) node_selectors labels.
    """
    labels = node.metadata.labels or {}
    return len(node_selectors) > 0 and all(
        labels.get(k) == v for k, v in node_selectors.items()
    )


def _container_resource_count(container, resource_name: str):
    """
    Internal. Number of units of an extended resource requested by a container.
    """
    if container.resources is None:
        return 0
    requests = container.resources.requests or {}
    limits = container.resources.limits or {}
    return int(requests.get(resource_name, limits.get(resource_name, 0)))


def _pod_resource_count(pod, resource_name: str):
    """Effective scheduling request, including init containers and native sidecars."""
    app_count = sum(
        _container_resource_count(container, resource_name)
        for container in pod.spec.containers
    )
    sidecar_count = 0
    init_count = 0
    for container in pod.spec.init_containers or []:
        count = _container_resource_count(container, resource_name)
        if getattr(container, "restart_policy", None) == "Always":
            sidecar_count += count
            init_count = max(init_count, sidecar_count)
        else:
            init_count = max(init_count, sidecar_count + count)
    return max(app_count + sidecar_count, init_count)


def _accelerator_node_selector(accelerator) -> Dict[str, str]:
    """Use configured labels; retain the product-label fallback for older catalogs."""
    return accelerator.get(
        "node_selector", {"nvidia.com/gpu.product": accelerator["name"]}
    )


async def _exporter_ips_async():
    async with kubernetes_api() as k:
        pods = await k.list_namespaced_pod(
            namespace=DCGM_EXPORTER_NAMESPACE,
            label_selector=DCGM_EXPORTER_LABEL,
            field_selector="status.phase=Running",
        )
    return [p.status.pod_ip for p in pods.items if p.status.pod_ip]
    # TODO: Here we should add the constraint to skip reserved nodes


async def list_exporter_ips():
    try:
        return await _exporter_ips_async()
    except Exception as error:
        logging.warning("[GPU-DISCOVERY] %s", error)
        return []


def fetch_metrics(ip, retries=3, delay=0.5):
    url = f"http://{ip}:{DCGM_METRICS_PORT}/metrics"
    for _ in range(retries):
        try:
            response = requests.get(url, timeout=2)
            if response.ok:
                return response.text
        except Exception:
            pass
        time.sleep(delay)
    return ""


def _labels(txt):
    return {k: v.strip('"') for k, v in SPLIT_RE.findall(txt)}


def parse_usage(text):
    # Keep the parsing and device accounting identical to corso-monaco.
    entity = {}
    usage = defaultdict(lambda: {"total": 0, "used": 0})
    for line in text.splitlines():
        if line.startswith("#") or "{" not in line:
            continue
        metric, _ = line.split("{", 1)
        m = LABELS_RE.search(line)
        if not m:
            continue
        lbl, val = m.groups()
        labels = _labels(lbl)
        value = float(val)
        model = labels.get("modelName")
        gpu_id = labels.get("gpu")
        mig_id = labels.get("GPU_I_ID")
        profile = labels.get("GPU_I_PROFILE")
        if not model or not gpu_id:
            continue
        key, name = (
            ((labels.get("UUID"), mig_id), f"{model} ({profile})")
            if mig_id
            else ((gpu_id,), model)
        )
        ent = entity.setdefault(key, {"name": name, "used": False})
        if any(k in labels for k in ("container", "pod", "namespace")):
            ent["used"] = True
        elif metric == "DCGM_FI_DEV_GPU_UTIL" and value > 0:
            ent["used"] = True

    for e in entity.values():
        usage[e["name"]]["total"] += 1
        usage[e["name"]]["used"] += 1 if e["used"] else 0
    return usage


def current_gpu_inventory(ips):
    inv = defaultdict(lambda: {"total": 0, "used": 0})
    for ip in ips:
        txt = fetch_metrics(ip)
        if not txt:
            continue
        for n, v in parse_usage(txt).items():
            inv[n]["total"] += v["total"]
            inv[n]["used"] += v["used"]
    return [{"name": n, **v} for n, v in inv.items()]


async def _dcgm_inventory():
    ips = await list_exporter_ips()
    logging.info("[GPU-DISCOVERY] exporter IPs: %s", ips)
    inventory = await asyncio.to_thread(current_gpu_inventory, ips)
    logging.info("[GPU-DISCOVERY] GPU inventory: %s", json.dumps(inventory))
    return inventory


################################################################################
## InfnSpawner
class InfnSpawner(KubeSpawner):
    @staticmethod
    def is_node_reserved(node, groups):
        if node.spec.taints is None:
            return False

        for taint in node.spec.taints:
            if taint.key == "reserved":
                if taint.value not in groups:
                    logging.warning(
                        f"Node {node.metadata.name} skipped as reserved to '{taint.value}' group. "
                        f"User groups: {groups}."
                    )
                    return True

        return False

    @staticmethod
    def is_node_virtual(node, groups):
        if node.spec.taints is None:
            return False

        for taint in node.spec.taints:
            if taint.key == "virtual-node.interlink/no-schedule":
                return True

        return False

    @staticmethod
    async def may_run_on_virtual_node(node_selector: Dict[str, str]):
        """
        True if any virtual (interLink) node matches node_selector, i.e. a session
        pinned to it may be scheduled on a virtual node.
        """
        async with kubernetes_api() as k:
            nodes = await k.list_node()

        return any(
            _node_matches(node, node_selector) and InfnSpawner.is_node_virtual(node, ())
            for node in nodes.items
        )

    @staticmethod
    async def get_accelerators(
        status_key: Literal["allocated", "allocatable", "capacity"] = "allocatable",
        default_extended_resource: str = "nvidia.com/gpu",
        groups: Collection[str] = tuple(),
        dcgm_inventory=None,
    ):
        """
        Complete the list of known accelerators with the number of
        available extended_resources as retrieved from the Node.

        Return the list defined in GPU_MODEL_DESCRIPTION with an additional
        `count` key reporting the number of each known accelerator model.

        GPU totals and usage come directly from DCGM.
        FPGA totals use node resources and allocations use JHUB_NAMESPACE pods.

        DCGM discovery uses the gpu-operator pod-reader.
        """

        async with kubernetes_api() as k:
            nodes = await k.list_node()

        # Copy the list
        return_list = [dict(**acc, count=0) for acc in GPU_MODEL_DESCRIPTION]

        visibile_nodes = [
            node
            for node in nodes.items
            if not InfnSpawner.is_node_reserved(node, groups)
        ]
        matching_models = {}
        for node in visibile_nodes:
            matching_models[node.metadata.name] = [
                acc
                for acc in return_list
                if acc.get("type") == "fpga"
                and _node_matches(node, _accelerator_node_selector(acc))
            ]

        if status_key in ["allocatable", "capacity"]:
            for node in nodes.items:
                node_resources = getattr(node.status, status_key, None) or {}
                for acc in matching_models.get(node.metadata.name, []):
                    ext_res = acc.get("extended_resource", default_extended_resource)
                    acc["count"] += int(node_resources.get(ext_res, 0))

        elif status_key in ["allocated"]:
            async with kubernetes_api() as k:
                pods = await k.list_namespaced_pod(namespace=JHUB_NAMESPACE)

            for pod in pods.items:
                if pod.status.phase in ["Succeeded", "Failed"]:
                    continue
                for acc in matching_models.get(pod.spec.node_name, []):
                    ext_res = acc.get("extended_resource", default_extended_resource)
                    acc["count"] += _pod_resource_count(pod, ext_res)

        else:
            raise KeyError(f"Unexpected status_key {status_key}")

        if dcgm_inventory is None:
            dcgm_inventory = await _dcgm_inventory()
        for acc in return_list:
            if acc.get("type") != "gpu":
                continue
            dcgm_names = acc.get("dcgm_names", [acc["name"]])
            readings = [row for row in dcgm_inventory if row["name"] in dcgm_names]
            key = "used" if status_key == "allocated" else "total"
            acc["count"] = sum(row[key] for row in readings)

        return return_list

    @staticmethod
    async def get_available_accelerators(groups: Collection[str] = tuple()):
        """Use one DCGM snapshot for GPU totals and usage"""
        inventory = await _dcgm_inventory()
        accelerators = await InfnSpawner.get_accelerators(
            groups=groups, dcgm_inventory=inventory
        )
        allocated = {
            acc["name"]: acc["count"]
            for acc in await InfnSpawner.get_accelerators(
                "allocated", groups=groups, dcgm_inventory=inventory
            )
        }
        for acc in accelerators:
            acc["occupied"] = allocated.get(acc["name"], 0)
            acc["avail"] = max(0, acc["count"] - acc["occupied"])
        return accelerators

    async def options_from_form(self, formdata):
        options = {}

        options["flavor"] = formdata["flavor"]
        flavor = "".join(formdata["flavor"])

        flavor_spec = {
            "cpu-1c4g": {"cpu": 1, "mem": "4G", "accelerator": "none"},
            "cpu-2c12g": {"cpu": 2, "mem": "12G", "accelerator": "none"},
            "gpu-3c16g": {"cpu": 3, "mem": "16G", "accelerator": "gpu"},
            "fpga-3c16g": {"cpu": 3, "mem": "16G", "accelerator": "fpga"},
            "fpga-3c16g-local": {"cpu": 3, "mem": "16G", "accelerator": "none"},
        }.get(flavor)

        if flavor_spec is None:
            raise Exception(f"Unknown flavor: {flavor}")

        if flavor in ["fpga-3c16g", "fpga-3c16g-local"]:
            self.image = FPGA_FORCED_IMAGE
        else:
            self.image = "".join(formdata["img"])

        options["img"] = [self.image]

        cpu = str(flavor_spec["cpu"])
        self.cpu_guarantee = 1.0
        self.cpu_limit = float(cpu)

        memory = flavor_spec["mem"]
        self.mem_guarantee = "2G"
        self.mem_limit = memory

        # self.extra_resource_guarantees = {k: 1 for k in EXTENDED_RESOURCES}
        # self.extra_resource_limits =  {k: 1 for k in EXTENDED_RESOURCES}

        # The spawner object is reused across server restarts: drop accelerator settings from a previous session
        self.extra_resource_guarantees = {}
        self.extra_resource_limits = {}
        self.tolerations = [
            t
            for t in self.tolerations
            if t.get("key") != "virtual-node.interlink/no-schedule"
        ]
        self.node_affinity_required = []
        self.node_affinity_preferred = []
        self.extra_pod_config = {
            k: v for k, v in self.extra_pod_config.items() if k != "runtimeClassName"
        }
        self.on_virtual_node = False
        self.is_fpga_session = False

        accelerator = flavor_spec["accelerator"]
        if accelerator in ["gpu", "fpga"]:
            accelerator_models = [
                acc
                for acc in await self.get_available_accelerators(self.get_user_groups())
                if acc.get("type") == accelerator
                and acc.get("name") not in ["none"]
                and acc["avail"] > 0
            ]
            if len(accelerator_models) == 0:
                raise Exception(
                    f"No available accelerator model for flavor type '{accelerator}'"
                )
            accelerator = f"{accelerator}:{accelerator_models[0]['name']}:1"

        if accelerator in ["none"]:
            self.node_affinity_preferred = [
                _prefer_accelerator(
                    acc.get(
                        "node_selector", {"nvidia.com/gpu.product": acc.get("name")}
                    ),
                    weight=acc.get("preference_weight", 50),
                )
                for acc in GPU_MODEL_DESCRIPTION
            ]

        elif accelerator.startswith("gpu:"):
            options["gpu"] = True

            _, model_gpu, n_gpus = accelerator.split(":")
            gpu_data = {g["name"]: g for g in GPU_MODEL_DESCRIPTION}.get(model_gpu)
            if gpu_data is None:
                raise Exception(f"Failed retrieving data for GPU model {model_gpu}")

            ext_res = gpu_data.get("extended_resource", "nvidia.com/gpu")
            self.extra_resource_guarantees.update({ext_res: n_gpus})
            self.extra_resource_limits.update({ext_res: n_gpus})

            self.tolerations.append(
                {
                    "key": f"nvidia.com/gpu",
                    "operator": "Exists",
                    "effect": "PreferNoSchedule",
                }
            )

            # Different GPU models may share nvidia.com/gpu: require the selected model.
            self.node_affinity_required = [
                _prefer_accelerator(_accelerator_node_selector(gpu_data))["preference"]
            ]

            self.extra_pod_config.update(
                {
                    "runtimeClassName": "nvidia",
                }
            )

        elif accelerator.startswith("fpga:"):
            options["fpga"] = True
            self.is_fpga_session = True

            _, model_fpga, n_fpgas = accelerator.split(":")
            fpga_data = {
                a["name"]: a for a in GPU_MODEL_DESCRIPTION if a.get("type") == "fpga"
            }.get(model_fpga)
            if fpga_data is None:
                raise Exception(f"Failed retrieving data for FPGA model {model_fpga}")

            ext_res = fpga_data.get("extended_resource", "xilinx.com/fpga")
            self.extra_resource_guarantees = {
                **self.extra_resource_guarantees,
                ext_res: n_fpgas,
            }
            self.extra_resource_limits = {
                **self.extra_resource_limits,
                ext_res: n_fpgas,
            }

            # FPGA nodes may be virtual (interLink) nodes
            self.tolerations = self.tolerations + [
                {
                    "key": "virtual-node.interlink/no-schedule",
                    "operator": "Exists",
                    "effect": "NoSchedule",
                }
            ]

            # On a virtual node the NFS volumes are mounted through the interLink
            # mesh, and the NFS server squashes root coming from there: start.sh,
            # running as root, cannot even enter the user's home. Such sessions
            # start directly as the user (see start()).
            self.on_virtual_node = await self.may_run_on_virtual_node(
                fpga_data["node_selector"]
            )

            # Pin the pod to nodes of the selected FPGA model (several models may share the resource name)
            self.node_affinity_required = [
                _prefer_accelerator(fpga_data["node_selector"])["preference"]
            ]
            self.node_affinity_preferred = []

            # No GPU runtime for FPGA sessions
            self.extra_pod_config = {
                k: v
                for k, v in self.extra_pod_config.items()
                if k != "runtimeClassName"
            }

        self.tolerations += [
            {"key": "reserved", "operator": "Equal", "value": g, "effect": "NoSchedule"}
            for g in self.get_user_groups()
        ]

        self.tolerations += [
            {
                "key": "reserved",
                "operator": "Equal",
                "value": g,
                "effect": "PreferNoSchedule",
            }
            for g in self.get_user_groups()
        ]

        logging.info("Affinity - preferred")
        logging.info(self.node_affinity_preferred)
        return options

    async def start(self):
        """
        Set the container identity for this session, then start it.

        Sessions normally start as root, so that start.sh can rename the user,
        fix the UID and grant sudo before dropping privileges. Sessions that may
        run on a virtual node start as the NFS user instead (on_virtual_node):
        start.sh then skips the root-only setup, and GRANT_SUDO has no effect.

        NB_UID, NB_GID and NB_GROUPS are only known here: setup_nfs_user sets
        them in the authenticator's pre_spawn_start, after options_from_form.
        """
        container_config = copy.deepcopy(NOTEBOOK_CONTAINER_CONFIG)

        # The spawner object is reused across server restarts: undo what a
        # previous session running as the user changed
        if not hasattr(self, "_configured_supplemental_gids"):
            self._configured_supplemental_gids = list(self.supplemental_gids)
            self._configured_extra_annotations = dict(self.extra_annotations)
            self._configured_start_timeout = self.start_timeout
            self._configured_http_timeout = self.http_timeout
        if getattr(self, "_home_set_for_user", False):
            self.environment.pop("HOME", None)
            self._home_set_for_user = False
        self.supplemental_gids = list(self._configured_supplemental_gids)
        self.extra_annotations = dict(self._configured_extra_annotations)
        self.start_timeout = self._configured_start_timeout
        self.http_timeout = self._configured_http_timeout

        if getattr(self, "on_virtual_node", False):
            username = self.get_user_name()
            group_ids = [
                int(entry.split(":")[0])
                for entry in self.environment.get("NB_GROUPS", "").split(", ")
                if entry
            ]
            # container_config["securityContext"].update(
            #     runAsUser=int(self.environment["NB_UID"]),
            #     runAsGroup=int(self.environment["NB_GID"]),
            # )
            # users (100) owns the image's writable paths; the project groups own
            # the shared directories, which start.sh can no longer join as root.
            # root (0) can write /etc/passwd, where start.sh adds the entry naming
            # NB_UID: without it the uid has no name ("I have no name!"). It is
            # only a group, and the NFS server squashes gid 0 anyway.
            self.supplemental_gids = sorted(
                set(self.supplemental_gids + [0, 100] + group_ids)
            )
            # Without the root setup the passwd entry keeps /home/jovyan as home
            self.environment["HOME"] = f"/{HOME_NAME}/{username}"
            self._home_set_for_user = True
            # MTU of the interLink mesh (WireGuard) interface. The tunnel carries
            # WireGuard in a WebSocket over TCP, so the path MTU does not limit it:
            # larger packets mean fewer of them through the user-space hops.
            self.extra_annotations["interlink.eu/wg-mtu"] = str(VIRTUAL_NODE_WG_MTU)
            # Wait for the pod to run, and then for its server to answer, long
            # enough to cover the whole offloading sequence
            self.start_timeout = VIRTUAL_NODE_START_TIMEOUT
            self.http_timeout = VIRTUAL_NODE_START_TIMEOUT
            self.log.info(
                f"Session of {username} may run on a virtual node: starting as "
                f"{self.environment['NB_UID']}:{self.environment['NB_GID']} "
                f"with supplemental groups {self.supplemental_gids}"
            )

        self.extra_container_config = container_config
        return await super().start()

    #################################################################################
    #### SPLASH AND AUTHORIZATION
    #### ------------------------
    #### This section has to be handled using the request module and calling an external service via APIs

    @property
    def splash_manager(self):
        if not hasattr(self, "_splash_manager"):
            self._splash_manager = SplashManager(
                NFS_MOUNT_POINT / NFS_VOLUME_PREFIX / "system" / "www" / "splash.html"
            )

        return self._splash_manager

    def get_user_name(self):
        return self.oauth_client_id[len("jupyterhub-user-") :]

    def get_user_groups(self):
        return [
            group.name
            for group in self.user.groups
            if not group.properties.get("system", False)
        ]

    def get_user_storage(self):
        return [
            group.properties.get("storage")
            for group in self.user.groups
            if "storage" in group.properties
        ]

    def check_privilege(self, op):
        system_groups = [
            g.name for g in self.user.groups if g.properties.get("system", False)
        ]
        result = op in system_groups
        logging.info(
            f"{self.get_user_name()} {'has' if result else 'has not'} permission '{op}'"
        )
        return result

    def get_group_allowance(self, resource):
        str_allowances = [
            g.properties.get(resource)
            for g in self.user.groups
            if resource in g.properties.keys()
        ]
        ret = []
        for allowance in str_allowances:
            try:
                ret.append(int(allowance))
            except ValueError:
                logging.error(
                    f"Failed allowance validation for {resource}: invalid value {allowance}."
                )

        return sorted(list(set(ret)))

    #################################################################################
    #### VOLUMES
    #### -------

    @staticmethod
    def initialize_nfs_volumes():
        if NFS_SERVER_ADDRESS is not None:
            os.chmod(NFS_MOUNT_POINT / NFS_VOLUME_PREFIX, 0o711)
            for name in ["system/envs", "shared/public"] + [
                f"system/{volume}" for volume in SYSTEM_VOLUMES
            ]:
                os.makedirs(NFS_MOUNT_POINT / NFS_VOLUME_PREFIX / name, exist_ok=True)
                os.chmod(NFS_MOUNT_POINT / NFS_VOLUME_PREFIX / name, 0o2777)

            setup_filepath = Path(
                f"{NFS_MOUNT_POINT}/{NFS_VOLUME_PREFIX}/{STARTUP_SCRIPT}".replace(
                    "//", "/"
                ).replace("//", "/")
            )
            setup_filepath_src = CONFIGMAP_MOUNT_PATH / "bootstrap-envs-setup.sh"

            if not os.path.exists(setup_filepath):
                logging.info(
                    f"Initializing setup script, {setup_filepath_src} -> {setup_filepath}"
                )
                shutil.copy2(setup_filepath_src, setup_filepath)
                os.chmod(setup_filepath, 0o666)
            else:
                logging.info(
                    f"Refuse to overwrite {setup_filepath} with {setup_filepath_src}"
                )

        else:
            logging.warning(
                "NFS_SERVER_ADDRESS not set. Will not mount network drivers."
            )

    def empty_volume(self, name, size_limit="1M"):
        return dict(
            name=name,
            emptyDir=dict(
                sizeLimit=size_limit,
            ),
        )

    def nfs_volume(self, name):
        return dict(
            name=name.replace("/", "-").replace(".", "-"),
            nfs=dict(server=NFS_SERVER_ADDRESS, path=f"/{NFS_VOLUME_PREFIX}/{name}"),
        )

    def nfs_mount(self, name, path, protected=False):
        return dict(
            name=name.replace("/", "-").replace(".", "-"),
            mountPath=path,
        )

    def jfs_volume(self):
        return dict(
            name=JUICEFS_PVC_NAME,
            persistentVolumeClaim=dict(
                claimName=JUICEFS_PVC_NAME,
            ),
        )

    def jfs_mount(self, name, path, protected=False):
        if not os.path.exists(JUICEFS_MOUNT_POINT / name):
            os.mkdir(JUICEFS_MOUNT_POINT / name)

        return dict(
            name=JUICEFS_PVC_NAME,
            mountPath=path,
            subPath=name,
        )

    @property
    def volumes(self):
        username = self.get_user_name()

        volumes = [
            self.empty_volume("secret-mask", size_limit="1M"),
            self.empty_volume("shared-memory", size_limit="32Gi"),
            self.empty_volume("tmp", size_limit="100Gi"),
        ]

        # if getattr(self, "is_fpga_session", False):
        #     volumes.append(
        #         dict(
        #             name=FPGA_INPUT_DATA_VOLUME,
        #             hostPath=dict(path=FPGA_INPUT_DATA_HOST_PATH, type="Directory"),
        #         )
        #     )

        if NFS_SERVER_ADDRESS is not None:
            volumes += [
                self.nfs_volume(f"{username}"),
                self.nfs_volume(f"shared/public"),
                self.nfs_volume(f"system/envs"),
            ]

            if self.check_privilege("juicefs"):
                volumes.append(self.jfs_volume())

            for volume in SYSTEM_VOLUMES:
                if self.check_privilege(volume):
                    volumes.append(self.nfs_volume(f"system/{volume}"))

            for group in self.get_user_groups():
                volumes += [self.nfs_volume(f"shared/{group}")]

            if CVMFS_CLAIM_NAME != "":
                volumes.append(
                    dict(
                        name="public-cvmfs",
                        persistentVolumeClaim={"claimName": CVMFS_CLAIM_NAME},
                    )
                )

            if self.check_privilege("slurm"):
                slurm_groups = [g for g in self.user.groups if g.name == "slurm"]
                assert len(slurm_groups) >= 1, (
                    "User is both member and non-member. Check logics."
                )
                cluster_name_namespace = (
                    slurm_groups[0].properties.get("cluster").split(".")
                )
                if len(cluster_name_namespace) == 1:
                    cluster_name = cluster_name_namespace[0]
                    cluster_namespace = "slurm"
                else:
                    cluster_name, cluster_namespace, *_ = cluster_name_namespace

                logging.info(
                    f"{self.get_user_name()} has access to cluster {cluster_name} in namespace {cluster_namespace}."
                )

                # Notice! The secret must be made available in the namespace where the notebook is spawned.
                # For example,
                # $ k get secret -n slurm slurm-<cluster_name>-auth-slurm -o yaml \
                #   | sed '/namespace:/d;/resourceVersion:/d;/uid:/d;/creationTimestamp:/d' \
                #   | k apply -n <namespace> -
                volumes.append(
                    dict(
                        name="slurm-config",
                        projected=dict(
                            defaultMode=0o400,
                            sources=[
                                dict(
                                    secret=dict(
                                        name=f"slurm-{cluster_name}-auth-slurm",
                                        keys=[dict(key="slurm.key", path="slurm.key")],
                                    )
                                )
                            ],
                        ),
                    )
                )

        return volumes

    @property
    def volume_mounts(self):
        username = self.get_user_name()
        volumes = [
            {
                "name": "secret-mask",
                "mountPath": "/var/run/secrets/kubernetes.io/serviceaccount",
                "readOnly": True,
            },
            {"name": "shared-memory", "mountPath": "/dev/shm", "readOnly": False},
            {"name": "tmp", "mountPath": "/tmp", "readOnly": False},
        ]

        if ALLOW_HOST_PATHS_ON_REMOTE:
            if getattr(self, "is_fpga_session", False):
                volumes.append(
                    {
                        "name": FPGA_INPUT_DATA_VOLUME,
                        "mountPath": FPGA_INPUT_DATA_MOUNT_PATH,
                    }
                )

        if NFS_SERVER_ADDRESS is not None:
            volumes += [
                {"name": f"{username}", "mountPath": f"/{HOME_NAME}/{username}"},
                {"name": "shared-public", "mountPath": f"/{HOME_NAME}/shared/public"},
                {
                    "name": "system-envs",
                    "mountPath": "/envs",
                    "readOnly": not self.check_privilege("envs"),
                },
            ]

            if JUICEFS_ENABLED and self.check_privilege("juicefs"):
                volumes.append(
                    self.jfs_mount(
                        f"jfs-user-{username}", f"/home/jfs/private/{username}"
                    )
                )

            for volume in SYSTEM_VOLUMES:
                if self.check_privilege(volume):
                    volumes += [
                        {
                            "name": f"system-{volume}",
                            "mountPath": f"/{HOME_NAME}/system/{volume}",
                        }
                    ]

            for group in self.get_user_groups():
                volumes += [
                    {
                        "name": f"shared-{group}",
                        "mountPath": f"/{HOME_NAME}/shared/{group}",
                        "readOnly": False,
                    }
                ]
                if JUICEFS_ENABLED and self.check_privilege("juicefs"):
                    volumes.append(
                        self.jfs_mount(
                            f"jfs-shared-{group}", f"/home/jfs/shared/{group}"
                        )
                    )

            if CVMFS_CLAIM_NAME != "":
                volumes.append(
                    dict(
                        name="public-cvmfs",
                        mountPath="/cvmfs",
                        mountPropagation="HostToContainer",
                    )
                )

            if self.check_privilege("slurm"):
                volumes.append(
                    dict(
                        name="slurm-config",
                        mountPath="/mnt/slurm",
                        readOnly=True,
                    )
                )

        return volumes

    #################################################################################
    #### INITIALIZATION SCRIPT
    #### ---------------------

    # @property
    # def lifecycle_hooks(self):
    #     storage = self.get_user_storage()
    #     if NFS_SERVER_ADDRESS is not None:
    #         return {
    #             "postStart": {
    #               "exec": {
    #                 # "command": ["sudo", "-u", self.get_user_name(), "/bin/bash", str(STARTUP_SCRIPT)] + storage
    #                 "command": [
    #                     "/bin/bash",
    #                     "-c",
    #                     f"""
    #                     if [ -r /envs/root_setup.sh ]; then
    #                         source /envs/root_setup.sh &> /tmp/setup.log
    #                     fi
    #                     """
    #                   ]
    #                 }
    #               }
    #           }
    #
    #     return dict()

    #################################################################################
    #### ADDITIONAL SERVICES
    #### -------------------

    @property
    def service_account(self):
        if ENABLE_VKD:
            return (
                VKD_ADMIN_SERVICE_ACCOUNT
                if self.check_privilege("vkd")
                else VKD_USER_SERVICE_ACCOUNT
            )
        else:
            return None

    @property
    def extra_containers(self):
        extra_containers = []
        if ENABLE_VKD:
            extra_containers.append(
                self._extra_container_virtual_kubelet_dispatcher,
            )

        return extra_containers

    @property
    def _extra_container_virtual_kubelet_dispatcher(self):
        """
        Configure a sidecar container for dispatching jobs via kueue,
        possibly using a virtual kueblet
        """
        environment = dict(
            BRANCH=VKD_IMAGE_BRANCH,
            INTERVAL="60",
            JUPYTERHUB_USERNAME=str(self.get_user_name()),
            JUPYTERHUB_GROUPS=":".join(self.get_user_groups()),
            ADMIN="true" if self.check_privilege(VKD_ADMIN_USER_GROUP) else "",
            PORT=str(VKD_PORT),
            HTTP_PREFIX=f"/user/{self.get_user_name()}/proxy/{VKD_PORT}",
            NAMESPACE=VKD_NAMESPACE,
            ORIGIN_NAMESPACE=JHUB_NAMESPACE,
            ACCELERATOR_MODELS=b64encode(
                json.dumps(GPU_MODEL_DESCRIPTION).encode("utf-8")
            ).decode("utf-8"),
        )

        if JUICEFS_ENABLED and self.check_privilege("juicefs"):
            environment.update(
                dict(
                    JUICEFS_S3_BUCKET=JUICEFS_S3_BUCKET,
                    JUICEFS_S3_ACCESS_KEY=JUICEFS_S3_ACCESS_KEY,
                    JUICEFS_S3_SECRET_KEY=JUICEFS_S3_SECRET_KEY,
                    JUICEFS_METADATA_DB=JUICEFS_METADATA_DB,
                    JUICEFS_FILESYSTEM_NAME=JUICEFS_FILESYSTEM_NAME,
                )
            )

        secrets = dict()

        return dict(
            name=VKD_SIDECAR_NAME,  # "vkd",
            imagePullPolicy=VKD_SIDECAR_PULLPOLICY,
            image=VKD_SIDECAR_IMAGE,  # "landerlini/vk-dispatcher:alpine.0",
            env=(
                [dict(name=k, value=v) for k, v in environment.items()]
                + [dict(name=k, valueFrom=v) for k, v in secrets.items()]
            ),
            volumeMounts=[
                v for v in self.volume_mounts if v["name"] not in ["secret-mask"]
            ],
        )


################################################################################
## Authentication setup

c.JupyterHub.tornado_settings = {
    "max_body_size": 1048576000,
    "max_buffer_size": 1048576000,
}
c.JupyterHub.log_level = 30

if AUTHENTICATOR == "GOOGLE":
    c.JupyterHub.authenticator_class = ConfigurableGoogleAuthenticator
    c.GoogleOAuthenticator.client_id = IAM_CLIENT_ID
    c.GoogleOAuthenticator.client_secret = IAM_CLIENT_SECRET
    c.GoogleOAuthenticator.allow_all = True
    c.GoogleOAuthenticator.manage_groups = False
    c.GoogleOAuthenticator.enable_auth_state = True
    c.GenericOAuthenticator.manage_groups = False
    c.GenericOAuthenticator.enable_auth_state = True

elif AUTHENTICATOR == "IAM":
    c.JupyterHub.authenticator_class = IamAuthenticator
    c.GenericOAuthenticator.oauth_callback_url = OAUTH_CALLBACK_URL

    c.GenericOAuthenticator.client_id = IAM_CLIENT_ID
    c.GenericOAuthenticator.client_secret = IAM_CLIENT_SECRET
    c.GenericOAuthenticator.authorize_url = OAUTH_ENDPOINT.strip("/") + "/authorize"
    c.GenericOAuthenticator.token_url = OAUTH_ENDPOINT.strip("/") + "/token"
    c.GenericOAuthenticator.userdata_url = OAUTH_ENDPOINT.strip("/") + "/userinfo"
    c.GenericOAuthenticator.scope = [
        "openid",
        "profile",
        "email",
        "address",
        "offline_access",
        "iam",
    ]  #'wlcg', 'wlcg.groups']
    c.GenericOAuthenticator.username_claim = lambda d: d["preferred_username"].replace(
        "_", ""
    )
    c.GenericOAuthenticator.manage_groups = False
    c.GenericOAuthenticator.enable_auth_state = True


################################################################################
## Spawner setup

c.JupyterHub.spawner_class = InfnSpawner
InfnSpawner.initialize_nfs_volumes()

# c.KubeSpawner.cmd = ["/usr/local/bin/start.sh"]
# c.KubeSpawner.args = ["--allow-root"]
# c.KubeSpawner.privileged = False
# c.KubeSpawner.allow_privilege_escalation = True

c.KubeSpawner.extra_pod_config = {
    "automountServiceAccountToken": True,
}

# c.KubeSpawner.environment = {
#   "HOME": f"/{HOME_NAME}/private",
#   "SHELL": "/bin/bash",
#   "JUPYTERHUB_SINGLEUSER_APP": "jupyter_server.serverapp.ServerApp",
# }

# c.KubeSpawner.extra_container_config = {
#    "securityContext": {
#            "privileged": False,
#            # "capabilities": {
#            #             "add": ["SYS_ADMIN"]
#            #         }
#        }
# }

c.JupyterHub.hub_connect_ip = "hub.jhub.svc.cluster.local"
# c.KubeSpawner.notebook_dir = f"/{HOME_NAME}"
# c.KubeSpawner.default_url = "/lab"

# MTU of the WireGuard mesh for sessions on interLink virtual nodes (the
# virtual kubelet defaults to 1280). The gateway side has to use the same value.
VIRTUAL_NODE_WG_MTU = int(os.environ.get("VIRTUAL_NODE_WG_MTU", "1420"))

# Sessions offloaded to an interLink virtual node start far more slowly than
# local ones: a DIND container is allocated, the mesh downloads its binaries and
# brings up WireGuard, and only then does the image start. START_TIMEOUT, sized
# for local pods, makes JupyterHub give up on a session that is still coming up
# (the pod then keeps running, with no server attached to it in the dashboard).
VIRTUAL_NODE_START_TIMEOUT = int(os.environ.get("VIRTUAL_NODE_START_TIMEOUT", "600"))

# Copied and adjusted per session by InfnSpawner.start()
NOTEBOOK_CONTAINER_CONFIG = {
    "imagePullPolicy": "Always",
    "securityContext": {
        "privileged": PRIVILEGED_USERS,
        # "allowPrivilegeEscalation": True,
        "runAsUser": 0,
        # "seccompProfile": {"type": "Unconfined"},
        # "capabilities": {
        #            "add": ["SYS_ADMIN", "CAP_CHROOT", "CAP_DAC_READ_SEARCH"]
        #        }
    },
}
c.KubeSpawner.extra_container_config = NOTEBOOK_CONTAINER_CONFIG

c.KubeSpawner.http_timeout = START_TIMEOUT
c.KubeSpawner.start_timeout = START_TIMEOUT


async def aiinfn_option_form(self):
    file_name = os.path.join(CONFIGMAP_MOUNT_PATH / "spawn_form.jinja2.html")
    groups = self.get_user_groups()
    accelerators = await self.get_available_accelerators(groups=groups)

    logging.info("Groups")
    logging.info([group.name for group in self.user.groups])
    logging.info([group.__dict__ for group in self.user.groups])

    id_vars = dict(
        username=self.get_user_name(),
        groups=self.get_user_groups(),
    )

    with open(file_name) as f:
        gpu_candidates = [
            acc
            for acc in accelerators
            if acc["count"] > 0
            and acc["name"] not in ["none"]
            and acc.get("type") == "gpu"
        ]
        fpga_candidates = [
            acc
            for acc in accelerators
            if acc["count"] > 0
            and acc["name"] not in ["none"]
            and acc.get("type") == "fpga"
        ]

        gpu_available = any(acc["avail"] > 0 for acc in gpu_candidates)
        fpga_available = any(acc["avail"] > 0 for acc in fpga_candidates)

        gpu_note = (
            f"({sum(acc['occupied'] for acc in gpu_candidates)}/{sum(acc['count'] for acc in gpu_candidates)} occupied)"
            if gpu_candidates
            else "(no GPU metrics available)"
        )
        fpga_note = (
            f"➡️ Milano ({sum(acc['count'] - acc['avail'] for acc in fpga_candidates)}/{sum(acc['count'] for acc in fpga_candidates)} occupied)"
            if fpga_candidates
            else "(no FPGA model configured)"
        )

        return jinja2.Template(f.read()).render(
            splash_message=self.splash_manager.message(**id_vars),
            **id_vars,
            flavors=[
                dict(
                    name="gpu-3c16g",
                    desc="🧬 Joint Fusion with GNNs in Medical Physics (3 CPU, 16 GB RAM, GPU)",
                    enabled=gpu_available,
                    default=False,
                    note=gpu_note,
                ),
                dict(
                    name="gpu-3c16g",
                    desc="🧮 Integrating Dynamical Systems with DNNs (3 CPU, 16 GB RAM, GPU)",
                    enabled=gpu_available,
                    default=False,
                    note=gpu_note,
                ),
                dict(
                    name="cpu-2c12g",
                    desc="⚛️ Quantum Machine Learning (2 CPU, 12 GB RAM, CPU-only)",
                    enabled=True,
                    default=not gpu_available,
                    note="",
                ),
                dict(
                    name="fpga-3c16g",
                    desc="🚀 4D Tracking on FPGA with NA62 data (3 CPU, 16 GB RAM, FPGA)",
                    enabled=fpga_available,
                    default=False,
                    note=fpga_note,
                ),
                dict(
                    name="fpga-3c16g-local",
                    desc="📍 4D Tracking with NA62 data (3 CPU, 16 GB RAM, CPU-only)",
                    enabled=True,
                    default=False,
                    note="Local deployment",
                ),
                dict(
                    name="cpu-1c4g",
                    desc="📂 File-system access, only (1 CPU, 4 GB RAM, CPU-only)",
                    enabled=True,
                    default=True,
                    note="",
                ),
            ],
            images=[dict(name=v, desc=k) for k, v in DEFAULT_JLAB_IMAGES.items()],
        )


c.KubeSpawner.options_form = aiinfn_option_form

################################################################################
## Metrics role setup

## Copy-pasted from:
## https://discourse.jupyter.org/t/how-can-prometheus-scrape-metrics-from-jupyterhub/2662/5
if METRICS_API_KEY is None:
    logging.warning(
        "JUPYTERHUB_METRICS_API_KEY not set. Dedicated role will not be set up."
    )
else:
    c.JupyterHub.services = [
        {
            "name": "service-prometheus",
            "api_token": METRICS_API_KEY,
        },
    ]

    c.JupyterHub.load_roles = [
        {
            "name": "service-metrics-role",
            "description": "access metrics",
            "scopes": [
                "read:metrics",
            ],
            "services": [
                "service-prometheus",
            ],
        }
    ]
