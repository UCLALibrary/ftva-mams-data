import xml.etree.ElementTree as ET
from xml.dom import minidom
import re
import os


def prettify(xml_string):
    """
    Beautify XML string while keeping empty elements fully typed out and removing extra lines.
    """
    parsed_xml = minidom.parseString(xml_string)
    pretty_xml = parsed_xml.toprettyxml(indent="  ")
    pretty_xml = "\n".join([line for line in pretty_xml.splitlines() if line.strip()])
    pretty_xml = re.sub(r"(<([\w\.\-:]+)[^>]*)(/>)", r"\1></\2>", pretty_xml)
    return pretty_xml


def copy_element(source_element, target_element):
    """
    Recursively copy source_element and its children to target_element.
    """
    for child in source_element:
        new_child = ET.SubElement(target_element, child.tag)
        new_child.text = child.text
        copy_element(child, new_child)  # Recursively copy sub-elements


def create_individual_xml_files(file_path, google_sheet_path):
    # Parse the first XML file
    tree = ET.parse(file_path)
    root = tree.getroot()

    # Parse the second XML file
    google_tree = ET.parse(google_sheet_path)
    google_root = google_tree.getroot()

    # Define the subfolder name
    output_folder = "Metadata_Files"

    # Create the subfolder if it doesn't exist
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)

    # Loop through each <ROW> element in the first XML
    for row in root.findall("ROW"):
        # Find the <inventory_id> and <inventory_no> sub-elements
        inventory_id = row.find("inventory_id")
        inventory_no = row.find("inventory_no")

        if (
            inventory_id is not None
            and inventory_id.text
            and inventory_no is not None
            and inventory_no.text
        ):
            # Find matching <MediaResource> elements in the second XML based on <inventory_no>
            matched_resources = [
                media_resource
                for media_resource in google_root.findall("MediaResource")
                if media_resource.find("Inventory_no") is not None
                and media_resource.find("Inventory_no").text == inventory_no.text
            ]

            # Only proceed if there are matches
            if matched_resources:
                # Create a new XML root element
                new_root = ET.Element("Root")

                # Copy all sub-elements of the original <ROW> recursively
                copy_element(row, new_root)

                # Create a <GoogleData> element to hold the matched <MediaResource> elements
                google_data = ET.SubElement(new_root, "GoogleData")
                for matched_resource in matched_resources:
                    # Add a copy of each matching <MediaResource> element
                    # to the <GoogleData> element.
                    # Add the <inventory_id> element to the copied <MediaResource>
                    inventory_id_element = ET.Element("inventory_id")
                    inventory_id_element.text = inventory_id.text
                    matched_resource.append(inventory_id_element)
                    google_data.append(matched_resource)

                # Convert the new XML tree to a string
                rough_string = ET.tostring(new_root, "utf-8")

                # Beautify the XML string while keeping empty elements fully typed out
                pretty_xml_as_string = prettify(rough_string.decode("utf-8"))

                # Create the new filename using both <inventory_no> and <inventory_id>
                new_file_name = f"{inventory_no.text}_{inventory_id.text}.xml"

                # Construct the full path to the new file in the subfolder
                new_file_path = os.path.join(output_folder, new_file_name)

                # Save the beautified XML to a file
                with open(new_file_path, "w", encoding="utf-8") as f:
                    f.write(pretty_xml_as_string)
                print(f"Created file: {new_file_path}")
            else:
                print(
                    f"No match found for inventory number {inventory_no.text}, skipping."
                )
        else:
            print(
                "No valid <inventory_no> or <inventory_id> found for this row, skipping."
            )


if __name__ == "__main__":
    # Specify the paths to your XML files
    input_file_path = "FMExport.xml"
    google_sheet_path = "ExportBatch_1.xml"
    create_individual_xml_files(input_file_path, google_sheet_path)
