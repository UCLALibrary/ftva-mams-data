import json
import spacy
import csv
from train_spacy import train_model, load_training_data

# for type hinting
from spacy.language import Language


def find_names(data: list, model: Language) -> dict:
    output_dict = {}
    for i in range(len(data)):
        subfield_c = data[i]
        current_names = []
        current_other_entities = []
        doc = model(subfield_c)
        for ent in doc.ents:
            if ent.label_ == "PERSON":
                current_names.append(ent.text)
            else:
                current_other_entities.append(ent.text)
        # add index to subfield_c so keys are unique
        dict_key = f"{subfield_c} ({i})"
        output_dict[dict_key] = {
            "names": current_names,
            "other_entities": current_other_entities,
        }

    return output_dict


def evaluate_model(data: list, model: Language, filename: str) -> None:
    entity_dict = find_names(data, model)
    # get total count of names and other entities
    total_names = 0
    total_other_entities = 0
    for key in entity_dict:
        total_names += len(entity_dict[key]["names"])
        total_other_entities += len(entity_dict[key]["other_entities"])

    print(f"total subfields: {len(entity_dict)}")
    print(f"total names: {total_names}")
    print(f"total other entities: {total_other_entities}")
    write_output_csv(filename, entity_dict)


def write_output_csv(file_name: str, output_dict: dict) -> None:
    with open(file_name, encoding="utf-8", mode="w") as file:
        writer = csv.writer(file)
        writer.writerow(["subfield_c", "names", "other_entities"])
        for key in output_dict:
            # remove index from key (index was added to make keys unique)
            subfield_c = key.split(" (")[0]
            writer.writerow(
                [
                    subfield_c,
                    output_dict[key]["names"],
                    output_dict[key]["other_entities"],
                ]
            )
    print(f"output written to {file_name}")


def main():
    with open("f245c_directors.txt", encoding="utf-8") as file:
        data = json.load(file)

    # concatenate each list of strings into a single string
    data = [" ".join(row) for row in data]

    small_model = spacy.load("en_core_web_sm")
    medium_model = spacy.load("en_core_web_md")

    print("small model:")
    evaluate_model(data, small_model, "small_model_output.csv")
    print()
    print("medium model:")
    evaluate_model(data, medium_model, "medium_model_output.csv")
    print()

    # train custom model
    training_data = load_training_data("training_data.txt")
    custom_model = train_model(training_data, medium_model)
    print("custom model:")
    evaluate_model(data, custom_model, "custom_model_output.csv")


if __name__ == "__main__":
    main()
