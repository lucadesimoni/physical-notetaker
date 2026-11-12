# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2026 Outthinkx by Luca De Simoni
"""
Swiss place names and dialect words as a help for transcribing
"""

import httpx
import pytest

from voxtral_notetaker import NotetakerConfig
from voxtral_notetaker.dialect import clean_lines, has_dialect
from voxtral_notetaker.places import place_hints, place_words


@pytest.mark.parametrize("text,words", [
    ("Wir treffen uns in Meltigen und essen danach in Langnau.", ["Meltigen", "Langnau"]),
    ("Mir fahre vo Pratteln uf Genpe.", ["Pratteln", "Genpe"]),
    ("Der Wettbewerb findet in Wolfhalden, Linthal und Lutzenberg statt.",
     ["Wolfhalden", "Linthal", "Lutzenberg"]),
    # Not places: no place word before, or a word that is never a place
    ("Hindelbank hat angerufen.", []),
    ("Im Herbst sehen wir uns in Zukunft öfter.", []),
])
def test_place_words(text, words):
    assert place_words(text) == words


def test_hints_for_misheard_places_only():
    hints = place_hints(["Wir treffen uns in Meltigen.", "Mir fahre vo Pratteln uf Genpe.",
                         "Im Herbst fahre ich nach Hinkubank, dann nach Bern."])
    assert "Meltingen" in hints["Meltigen"]
    assert "Gempen" in hints["Genpe"]
    assert hints["Hinkubank"] == ["Hindelbank"]
    # Heard as official names: trusted, no hints
    assert "Pratteln" not in hints and "Bern" not in hints


def test_hints_go_to_the_clean_up(monkeypatch):
    config = NotetakerConfig()
    config.voxtral.api_key = "k"
    sent = []

    def fake_post(url, headers, json, timeout):
        sent.append(json["messages"][0]["content"])
        return httpx.Response(200, json={"choices": [{"message": {"content": "1|Wir treffen uns in Meltingen."}}]},
                              request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", fake_post)
    assert clean_lines(["Wir treffen uns in Meltigen."], config) == ["Wir treffen uns in Meltingen."]
    assert "«Meltigen»: Meltingen" in sent[0] and "Rate nie" in sent[0]
    config.voxtral.place_hints = False
    clean_lines(["Wir treffen uns in Meltigen."], config)
    assert "«Meltigen»" not in sent[1]


@pytest.mark.parametrize("text", [
    "Das hät er nume gseit.",            # from the Swiss German Wikipedia word list
    "Mir müend das zwüsche de Sitzige mache.",
    "Er isch sälber cho.",
    "Im Summer bsuech ich Wohlen.",          # dialect verb and noun
    "S Ticket gültet für Frenkendorf.",      # dialect article before a noun
    "Mir mache Foti in Wegenstetten.",       # "Mir" + verb in -e
])
def test_dialect_words_from_corpus(text):
    assert has_dialect(text)


@pytest.mark.parametrize("text", [
    "Ich fahre morgen selber nach Bern und finde das gut.",
    "Das heisst, wir erinnern uns daran.",
    "Merci vielmals, Herr Präsident.",
    "Im Sommer besuche ich Wohlen.",
    "Das Ticket gilt für Frenkendorf.",
    "Mir ist das recht, Dr. Meier.",
])
def test_standard_german_is_not_dialect(text):
    assert not has_dialect(text)


def test_only_place_fixes_are_accepted_from_hints():
    from voxtral_notetaker.dialect import accept_change
    hints = {"Meltigen": ["Meltingen", "Mellingen"]}
    old = "Wir treffen uns morgen früh in Meltigen."
    assert accept_change(old, "Wir treffen uns morgen früh in Meltingen.", hints)
    # A place not in the hints, or polishing besides the place: not taken
    assert not accept_change(old, "Wir treffen uns morgen früh in Genf.", hints)
    assert not accept_change(old, "Wir sehen uns morgen früh in Meltingen.", hints)
