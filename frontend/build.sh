#!/bin/bash
cd "$(dirname "$0")/src"
mkdir -p ../dist
{
echo '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Bupa CareFlow Assistant V2</title><style>'
cat 01-style.css
echo '</style></head><body><div id="app"></div><div id="tip" role="tooltip"></div><script>'
cat 02-core.js 03-services.js 04-ui.js 05-modals.js 06-pages-a.js 07-pages-b.js 08-pages-c.js 10-v2-features.js 09-init.js
echo '</script></body></html>'
} > ../dist/index.html
wc -c ../dist/index.html
