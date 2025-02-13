import yaml

def extract_encodings(isax_yaml_path):
    isax = dict()
    with open(isax_yaml_path, 'r') as file:
        isax_desc = yaml.safe_load(file)
        if isax_desc:
            for item in isax_desc:
                if 'instruction' in item:
                    ins_name = item['instruction']
                    encoding = item['mask']
                    isax[ins_name] = encoding
    return isax
