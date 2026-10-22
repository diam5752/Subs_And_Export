#!/bin/sh
set -eu

# Some architectures in the same immutable upstream index still have PHP 8.4.26.
# Check the interpreter before accepting any web request, not its image metadata.
if ! php -r 'exit(PHP_VERSION_ID >= 80427 && PHP_VERSION_ID < 80500 ? 0 : 1);'; then
    printf '%s\n' 'Adminer blocked: a patched PHP 8.4 runtime (8.4.27 or later) is required.' >&2
    exit 1
fi

exec php -S '[::]:8080' -t /var/www/html
