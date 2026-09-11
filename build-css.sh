#!/bin/sh
# Stilleri derler. app.js veya index.html'e yeni bir Tailwind sınıfı
# eklendiğinde çalıştırın; aksi halde o sınıf stilsiz kalır.
npx --yes tailwindcss@3.4.17 -c tailwind.config.js -i tailwind.input.css -o site/styles.css --minify
