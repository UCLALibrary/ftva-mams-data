import pandas as pd
from xml.dom import minidom
import xml.etree.ElementTree as ET
import re


def prettify(xml_string):
    """
    Beautify XML string while keeping empty elements fully typed out.
    """
    # Parse the XML string with minidom
    parsed_xml = minidom.parseString(xml_string)
    pretty_xml = parsed_xml.toprettyxml(indent="  ")

    # Regular expression to replace minimized empty elements with fully typed-out elements
    # Matches tags like <tag/> and replaces them with <tag></tag>
    pretty_xml = re.sub(r"(<([\w\.\-:]+)[^>]*)(/>)", r"\1></\2>", pretty_xml)

    return pretty_xml


def create_xml_from_excel(file_path):
    # Load the Excel file into a DataFrame
    df = pd.read_excel(file_path)

    # Create the root XML element
    root = ET.Element("Root")

    # Iterate over the rows in the DataFrame
    for _, row in df.iterrows():
        # Create an element named MEDIARESOURCE for each row
        media_resource_elem = ET.SubElement(root, "MediaResource")

        for col in df.columns:
            col_elem = ET.SubElement(media_resource_elem, col)
            col_elem.text = str(row[col])

    # Convert the tree to a string
    xml_data = ET.tostring(root, encoding="utf-8")

    # Beautify the XML string while keeping empty elements fully typed out
    pretty_xml_as_string = prettify(xml_data.decode("utf-8"))

    # Define the output XML file name
    output_file = file_path.replace(".xlsx", ".xml")

    # Save the XML to a file
    with open(output_file, "w") as xml_file:
        xml_file.write(pretty_xml_as_string)

    print(f"XML file created successfully: {output_file}")


if __name__ == "__main__":
    # Directly use the specified file name
    excel_file_path = "ExportBatch_1.xlsx"
    create_xml_from_excel(excel_file_path)
