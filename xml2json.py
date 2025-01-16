import os
import json
import xml.etree.ElementTree as ET
from glob import glob


def xml_to_dict(element):
    """
    Recursively convert an XML element and its children to a dictionary.
    """
    result = {}
    if element.attrib:
        result["@attributes"] = element.attrib

    if element.text and element.text.strip():
        result["#text"] = element.text.strip()

    children = list(element)
    if children:
        child_dict = {}
        for child in children:
            child_result = xml_to_dict(child)
            if child.tag in child_dict:
                if not isinstance(child_dict[child.tag], list):
                    child_dict[child.tag] = [child_dict[child.tag]]
                child_dict[child.tag].append(child_result[child.tag])
            else:
                child_dict[child.tag] = child_result[child.tag]
        result.update(child_dict)
    else:
        # Set the leaf element's tag to its text content if present
        if element.text and element.text.strip():
            result = element.text.strip()
        else:
            result = None

    return {element.tag: result}


def convert_xml_to_json(input_folder, output_folder):
    """
    Convert all XML files in the input folder to JSON files in the output folder.
    """
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)

    xml_files = glob(os.path.join(input_folder, "*.xml"))

    for xml_file in xml_files:
        try:
            tree = ET.parse(xml_file)
            root = tree.getroot()

            data_dict = xml_to_dict(root)

            json_filename = os.path.splitext(os.path.basename(xml_file))[0] + ".json"
            json_filepath = os.path.join(output_folder, json_filename)

            with open(json_filepath, "w", encoding="utf-8") as json_file:
                json.dump(data_dict, json_file, indent=4, ensure_ascii=False)

            print(f"Converted: {xml_file} -> {json_filepath}")

        except Exception as e:
            print(f"Error processing {xml_file}: {e}")


if __name__ == "__main__":
    input_folder = input("Enter the path to the folder containing XML files: ")
    output_folder = input("Enter the path to the output folder for JSON files: ")

    convert_xml_to_json(input_folder, output_folder)
