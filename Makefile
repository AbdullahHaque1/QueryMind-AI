.PHONY: install build ask app eval

install:
	pip install -r requirements.txt

build:
	python -m src.build_db

ask:
	python -m src.cli "$(Q)"

app:
	streamlit run src/app.py

eval:
	python -m src.evaluate
