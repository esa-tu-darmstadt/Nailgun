import sys
import re


def extract_sections(file_content):
    architectural_state = re.search(
        r'architectural_state\s*{(.*?)^[ ]{2}}', file_content, re.DOTALL | re.MULTILINE)
    functions = re.search(
        r'functions\s*{(.*?)^[ ]{2}}', file_content, re.DOTALL | re.MULTILINE)
    instructions = re.search(
        r'instructions\s*{(.*?)^[ ]{2}}', file_content, re.DOTALL | re.MULTILINE)
    always = re.search(
        r'always\s*{(.*?)^[ ]{2}}', file_content, re.DOTALL | re.MULTILINE)

    return {
        'architectural_state': architectural_state.group(1).strip() if architectural_state else '',
        'functions': functions.group(1).strip() if functions else '',
        'instructions': instructions.group(1).strip() if instructions else '',
        'always': always.group(1).strip() if always else ''
    }


def merge_architectural_state(states):
    merged_state = []
    has_mem = False
    has_pc = False
    has_core_regs = False

    for state in states:
        lines = state.split('\n')
        for line in lines:
            stripped_line = line.strip()
            if "register unsigned<" in stripped_line:
                if "> PC;" in stripped_line:
                    if has_pc:
                        continue
                    else:
                        has_pc = True
                if "> X[" in stripped_line:
                    if has_core_regs:
                        continue
                    else:
                        has_core_regs = True
            elif "extern unsigned<" in stripped_line and "> MEM[" in stripped_line:
                if has_mem:
                    continue
                else:
                    has_mem = True

            merged_state.append(stripped_line)

    return '\n    '.join(merged_state)


def merge_files(file_paths):
    file_contents = []

    for file_path in file_paths:
        with open(file_path, 'r') as file:
            file_contents.append(file.read())

    merged_sections = {
        'architectural_state': [],
        'functions': '',
        'instructions': '',
        'always': ''
    }

    for content in file_contents:
        sections = extract_sections(content)
        if sections['architectural_state']:
            merged_sections['architectural_state'].append(
                sections['architectural_state'])
        for key in ['functions', 'instructions', 'always']:
            if sections[key]:
                if merged_sections[key]:
                    merged_sections[key] += '\n    ' + sections[key]
                else:
                    merged_sections[key] = sections[key]

    merged_architectural_state = merge_architectural_state(
        merged_sections['architectural_state'])

    fun_section = f"""
  functions {{
    {merged_sections['functions']}
  }}
""" if merged_sections['functions'] else ""
    always_section = f"""
  always {{
    {merged_sections['always']}
  }}
""" if merged_sections['always'] else ""

    # TODO do not hardcode sbox here, fuse the ISAX names
    isax_name = "merged"

    return f"""
InstructionSet {isax_name} {{
  architectural_state {{
    {merged_architectural_state}
  }}

{fun_section}

  instructions {{
    {merged_sections['instructions']}
  }}

{always_section}
}}
""", isax_name
