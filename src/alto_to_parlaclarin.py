from lxml import etree
import argparse
import random, string
from pyparlaclarin.refine import format_texts

TEI_NAMESPACE ="{http://www.tei-c.org/ns/1.0}"
ALTO_NAMESPACE = "{http://www.loc.gov/standards/alto/ns-v3#}"
XML_NAMESPACE = "{http://www.w3.org/XML/1998/namespace}"

XML_PARSER = etree.XMLParser(remove_blank_text=True)

def load_xml(path):
    with open(path) as f:
        root = etree.parse(f, XML_PARSER).getroot()
    return root

def populate_parlaclarin(parlaclarin, alto, alto_path):
    """
    Modify this function to convert the OCR'd ALTO file into a parlaclarin file

    Complete the TODOs, and check that the result matches
    """

    # Remove example elements
    body = parlaclarin.findall(f".//{TEI_NAMESPACE}body")[0]
    div = body.findall(f".//{TEI_NAMESPACE}div")[0]
    for elem in div:
        elem.getparent().remove(elem)

    # Create an element denoting the page
    pb = etree.SubElement(div, f"{TEI_NAMESPACE}pb")
    # TODO: Add link to file in the pb element as an attribute

    for TextBlock in alto.findall(f".//{ALTO_NAMESPACE}TextBlock"):
        # TODO: add paragraphs from alto
        # as 'note' elements inside the 'div' element
        paragraph_text = ""

        note = etree.SubElement(div, f"{TEI_NAMESPACE}note")
        note.text = paragraph_text

        # TODO: add a unique identifier to the element
        note.attrib[f"{XML_NAMESPACE}id"] = ""

    return parlaclarin


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--altopath", type=str, required=True, help="Path to the ALTO XML document")
    parser.add_argument("--template_path", type=str, default="data/template.xml", help="Path to the parlaclarin template")
    parser.add_argument("--outpath", type=str, required=True, help="Export path")
    args = parser.parse_args()

    parlaclarin = load_xml(args.template_path)
    alto = load_xml(args.altopath)

    parlaclarin = populate_parlaclarin(parlaclarin, alto, args.altopath)
    parlaclarin = format_texts(parlaclarin, padding=10)
    b = etree.tostring(
        parlaclarin, pretty_print=True, encoding="utf-8", xml_declaration=True
    )
    with open(args.outpath, "wb") as f:
        f.write(b)
