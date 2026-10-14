"""Text cleaning and tokenization for BM25 (sparse retrieval).

Steps, applied in the same way to passages and to queries:
  1. lowercase
  2. remove punctuation: every character that is not a letter or digit becomes a space
     ("withdrawal," -> "withdrawal", "2011/83/EU" -> "2011 83 eu")
  3. split into words
  4. remove English stopwords (NLTK list: "the", "of", "within", ...)
  5. Porter stemming: reduce words to their stem ("withdrawal" -> "withdraw", "days" -> "day"),
     so different forms of the same word match

NLTK keeps its stopword list in a separate data package. It is downloaded once into
the folder set in config.yaml (paths.nltk_data).
"""

import re
from pathlib import Path

import nltk
from nltk.stem import PorterStemmer

NOT_LETTER_OR_DIGIT = re.compile(r"[^a-z0-9]+")

# The original Porter (1980) algorithm, without NLTK's later extensions.
STEMMER = PorterStemmer(mode=PorterStemmer.ORIGINAL_ALGORITHM)


def load_stopwords(language: str, nltk_data_dir: Path) -> frozenset[str]:
    """Return NLTK's stopword list, downloading it into nltk_data_dir the first time."""
    nltk_data_dir = Path(nltk_data_dir)
    if str(nltk_data_dir) not in nltk.data.path:
        nltk.data.path.insert(0, str(nltk_data_dir))
    try:
        nltk.data.find("corpora/stopwords")
    except LookupError:
        nltk_data_dir.mkdir(parents=True, exist_ok=True)
        nltk.download("stopwords", download_dir=str(nltk_data_dir), quiet=True)
    from nltk.corpus import stopwords
    return frozenset(stopwords.words(language))


def normalise(text: str) -> str:
    """Steps 1-2: lowercase and replace punctuation with spaces."""
    return NOT_LETTER_OR_DIGIT.sub(" ", text.lower())


def tokenize(text: str, stopwords: frozenset[str]) -> list[str]:
    """Steps 1-5: the list of stemmed, meaningful words in the text."""
    return [STEMMER.stem(word) for word in normalise(text).split() if word not in stopwords]
