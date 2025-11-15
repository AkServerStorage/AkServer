# =============================================================================
# AkServer –  Software Module
# =============================================================================

"""
Description:    Embedded HTML content for akserver pages.
Author:         Akshay Shinde
Version:        1.0.0
License:        MIT License - See LICENSE file in the project root
                https://github.com/AkServerStorage/AkServer/blob/main/LICENSE

Copyright © 2025 Akshay Shinde. Open Source.

Permission is hereby granted to use, copy, modify, merge, publish, distribute,
sublicense, and/or sell copies of this software.

"""

import os, sys
from datetime import datetime
from jinja2 import Environment, FileSystemLoader

def get_webui_dir():
    try:
        base_path = sys._MEIPASS 
    except AttributeError:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, "html_temp")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WEBUI_DIR = os.path.join(BASE_DIR, "html_temp") 

env = Environment(loader=FileSystemLoader(WEBUI_DIR))

def get_html(template_name, **kwargs):
    """
    Render a template with Jinja2 and return fully processed HTML.
    """

    kwargs['current_year'] = kwargs.get('current_year', datetime.now().year)
    template = env.get_template(template_name)
    return template.render(**kwargs)


# ---------------- Example usage ----------------
if __name__ == "__main__":
    html = get_html(
        "upload.html",
        cache_buster="123456",
        upload_token="offline-token",
        user_name="Akshay",
        current_year=datetime.now().year
    )
