SHELL := /bin/sh

# Override these when invoking make, for example:
# make setup LIBRARY=/Volumes/Books IMPORTS=/Volumes/Inbox
DB ?= $(CURDIR)/data/library.sqlite3
LIBRARY ?= $(CURDIR)/example/library
IMPORTS ?= $(CURDIR)/example/imports
HOST ?= 127.0.0.1
PORT ?= 8686
PICKER ?=
RUN ?= uv run

.PHONY: help setup run scan organize list test clean-local

help:
	@printf '%s\n' 'Audiobook Library local commands:' \
	  '  make setup    Save the local library and import paths' \
	  '  make run      Start the web interface' \
	  '  make scan     Scan configured import paths' \
	  '  make organize Copy pending books into the library' \
	  '  make list     List known books' \
	  '  make test     Run unit tests' \
	  '' \
	  'Example: make setup LIBRARY=/Volumes/AudioBooks IMPORTS=/Volumes/Inbox'

setup:
	@mkdir -p "$(dir $(DB))"
	@AUDIOBOOK_LIB_DATABASE="$(DB)" $(RUN) audiobook-lib setup --library "$(LIBRARY)" --imports "$(IMPORTS)"

run:
	@mkdir -p "$(dir $(DB))"
	@AUDIOBOOK_LIB_DATABASE="$(DB)" $(RUN) audiobook-lib serve --host "$(HOST)" --port "$(PORT)" $(PICKER)

scan:
	@AUDIOBOOK_LIB_DATABASE="$(DB)" $(RUN) audiobook-lib scan

organize:
	@AUDIOBOOK_LIB_DATABASE="$(DB)" $(RUN) audiobook-lib organize

list:
	@AUDIOBOOK_LIB_DATABASE="$(DB)" $(RUN) audiobook-lib list

test:
	@$(RUN) python -m unittest discover -s tests -v

clean-local:
	@printf '%s\n' 'This target intentionally does not delete your database or media files.'
