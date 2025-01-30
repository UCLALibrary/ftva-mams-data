from spacy.training.example import Example
from spacy.language import Language


def _load_training_data(file_path: str) -> list:
    """Load training data from a text file.
    Data is formatted as text, followed by a newline,
    followed by a list of names separated by newlines.
    Each entry is separated by two newlines.
    """
    with open(file_path, encoding="utf-8") as file:
        data = file.read().split("\n\n")
        data = [item.split("\n") for item in data]

    # Data must be in a specific format for training spacy.
    return _format_training_data(data)


def _format_training_data(data: list) -> list:
    """Format training data for spacy."""
    formatted_data = []
    for item in data:
        text = item[0]
        entities = []
        for name in item[1:]:
            start = text.find(name)
            end = start + len(name)
            # TODO: Will this always be "PERSON", for our needs?
            entities.append((start, end, "PERSON"))
        formatted_data.append((text, {"entities": entities}))
    return formatted_data


def train_model(file_path: str, model: Language) -> Language:
    """Train a spacy NER model with the given data, loaded from a text file."""
    data = _load_training_data(file_path)

    # set up pipeline for training
    if "ner" not in model.pipe_names:
        ner = model.add_pipe("ner")
        model.add_pipe(ner, last=True)
    else:
        ner = model.get_pipe("ner")

    # get names of other pipes to disable them during training
    other_pipes = [pipe for pipe in model.pipe_names if pipe != "ner"]
    with model.select_pipes(disable=other_pipes):
        model.resume_training()
        for _ in range(10):
            losses = {}
            for text, annotations in data:
                doc = model.make_doc(text)
                example = Example.from_dict(doc, annotations)
                model.update([example], drop=0.5, losses=losses)
    return model
