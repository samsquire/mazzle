# Makefile
venv: venv/bin/activate
venv/bin/activate: requirements.txt
	test -d venv || python3 -m venv venv
	venv/bin/pip3 install -Ur requirements.txt
	touch venv/bin/activate
