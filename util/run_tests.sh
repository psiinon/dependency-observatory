#!/bin/bash

# requires a running api container
docker-compose exec api pytest \
	       -p no:cacheprovider \
	       -o 'filterwarnings=ignore:"@coroutine" decorator is deprecated.*:DeprecationWarning' \
	       "$@"