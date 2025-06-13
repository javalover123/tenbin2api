#!/bin/bash

start_xrdp_services() {
    rm -rf /var/run/xrdp-sesman.pid
    rm -rf /var/run/xrdp.pid
    rm -rf /var/run/xrdp/xrdp-sesman.pid
    rm -rf /var/run/xrdp/xrdp.pid

    xrdp-sesman &
    xrdp -n &

    echo "Waiting for X server to be ready..."
    for i in {1..20}; do
        if pgrep Xorg >/dev/null; then
            echo "Xorg is running."
            return
        fi
        sleep 1
    done

    echo "Xorg not detected after timeout."
}

stop_xrdp_services() {
    xrdp --kill
    xrdp-sesman --kill
    exit 0
}

if id "root" &>/dev/null; then
    echo "root:root" | chpasswd || {
        echo "Failed to update password."
        exit 1
    }
else
    if ! getent group root >/dev/null; then
        addgroup root
    fi

    useradd -m -s /bin/bash -g root root || {
        echo "Failed to create user."
        exit 1
    }
    echo "root:root" | chpasswd || {
        echo "Failed to set password."
        exit 1
    }
    usermod -aG sudo root || {
        echo "Failed to add user to sudo."
        exit 1
    }
fi

if [ -n "$TZ" ]; then
    ln -snf /usr/share/zoneinfo/$TZ /etc/localtime
    echo $TZ >/etc/timezone
fi

mkdir -p /root/Desktop

cd /root/Desktop || {
    echo "Failed to change directory to /root/Desktop"
    exit 1
}

git clone https://github.com/Theyka/Turnstile-Solver.git
cd Turnstile-Solver || {
    echo "Failed to change directory to Turnstile-Solver"
    exit 1
}

pip3 install -r requirements.txt --break-system-packages

trap "stop_xrdp_services" SIGKILL SIGTERM SIGHUP SIGINT EXIT
start_xrdp_services

if [ "$RUN_API_SOLVER" = "true" ]; then
    echo "Starting API solver in headful mode..."
    xvfb-run -a python3 /root/Desktop/Turnstile-Solver/api_solver.py --browser_type chrome --host 0.0.0.0
fi
