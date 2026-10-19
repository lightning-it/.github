"""Inert, deliberately unsafe data for an unmerged CodeQL qualification PR."""

import sqlite3
from flask import Flask, request

application = Flask(__name__)


@application.route("/codeql-qualification")
def qualification():
    name = request.args["name"]
    connection = sqlite3.connect(":memory:")
    connection.execute("SELECT id FROM samples WHERE name = '" + name + "'")
    return ""
