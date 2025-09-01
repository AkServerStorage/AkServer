# =============================================================================
# akserver - HTML Templates (Proprietary Edition)
# =============================================================================
"""
File: akserver_html.py
Description: Embedded HTML content for akserver pages.
Author: AkshAy S (akserver Project)
Version: 1.0.0
License: akserver Custom Freemium License (See LICENSE.txt)

© 2025 akserver. All rights reserved.

This software is proprietary and confidential.
Redistribution, modification, or reverse engineering is strictly prohibited
unless permitted by a commercial license agreement.

For license terms, visit: https://akserverstorage.github.io/akserver_announcement/license.html
"""

import os
from jinja2 import Environment, FileSystemLoader

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Point directly to current folder (akserver_webui)
WEBUI_DIR = BASE_DIR  

env = Environment(loader=FileSystemLoader(WEBUI_DIR))

def get_html(template_name, **kwargs):
    """
    Loads an HTML template and renders it with variables.
    """
    template = env.get_template(template_name)
    return template.render(**kwargs)



