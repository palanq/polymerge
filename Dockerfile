# polybot has no persistent state -- no database, no session, no config file:
# marks live in Discord reactions and every merge runs in its own temp dir. So
# the container is disposable and needs no volumes.
FROM python:3.12-slim

# PYTHONUNBUFFERED: the console log is the primary diagnostic (channel
# permission changes in particular are only ever visible there), and block
# buffering through a pipe would hide it until the buffer filled.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Only what the bot actually needs at runtime. tests/ is ~a hundred MB of
# screenshots and regenerable output; it has no business in the image.
#
# Overlays/ is not optional and used not to be here at all, which is a failure
# worth spelling out: polymerge fell back to a template_18x18/template_20x20
# pair that covered only two of the five sizes the bot advertises, so a
# container built without Overlays/ refused `!merge 11`, `!merge 14` and
# `!merge 16` outright, drew no decorative layer at any size, and registered 18
# and 20 against different fog art from the rest. Those two files and their
# fallback are gone, so this COPY is now the only thing standing between the
# bot and a startup refusal -- which is the intended behavior.
#
# Assets/ carries the Elyrion ruin sprite and the Assets/Heads/ tribe head
# catalog --overlays vision matches screenshots against. Missing either
# reports NO-RUIN-SPRITE/NO-HEAD-CATALOG and switches itself off; the merge
# still runs.
COPY polybot.py polymerge.py ./
COPY Overlays/ ./Overlays/
COPY Assets/ ./Assets/

RUN useradd --create-home --uid 10001 polybot
USER polybot

CMD ["python", "polybot.py"]
