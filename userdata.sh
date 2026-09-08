#!/bin/bash

dnf update -y

dnf install nginx -y

systemctl enable nginx
systemctl start nginx

dnf install stress-ng -y

echo "SRE Agent Test Server" > /usr/share/nginx/html/index.html