import spacy
from spacy.training.example import Example
from spacy.language import Language


def load_training_data(file_path: str) -> list:
    """Load training data from a text file.
    Data is formatted as text, followed by a newline,
    followed by a list of names separated by newlines.
    Each entry is separated by two newlines.
    """

    with open(file_path, encoding="utf-8") as file:
        data = file.read().split("\n\n")
        data = [item.split("\n") for item in data]
        return data


def _format_training_data(data: list) -> list:
    """Format training data for spacy."""
    formatted_data = []
    for item in data:
        text = item[0]
        entities = []
        for name in item[1:]:
            start = text.find(name)
            end = start + len(name)
            entities.append((start, end, "PERSON"))
        formatted_data.append((text, {"entities": entities}))
    return formatted_data


def train_model(data: list) -> Language:
    """Train a spacy NER model with the given data, loaded from a text file."""
    formatted_data = _format_training_data(data)

    nlp = spacy.load("en_core_web_md")
    # set up pipeline for training
    if "ner" not in nlp.pipe_names:
        ner = nlp.add_pipe("ner")
        nlp.add_pipe(ner, last=True)
    else:
        ner = nlp.get_pipe("ner")

    # get names of other pipes to disable them during training
    other_pipes = [pipe for pipe in nlp.pipe_names if pipe != "ner"]
    with nlp.disable_pipes(*other_pipes):  # only train NER
        nlp.resume_training()
        for itn in range(10):
            losses = {}
            for text, annotations in formatted_data:
                doc = nlp.make_doc(text)
                example = Example.from_dict(doc, annotations)
                nlp.update([example], drop=0.5, losses=losses)
    return nlp
