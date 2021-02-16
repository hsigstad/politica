import sys
import yaml

with open('user-config.yaml', 'r') as stream:
    data = yaml.load(stream, Loader=yaml.FullLoader)

sys.path.append('{}/source'.format(data['base_dir']))
sys.path.append(data['diarios_dir'])

external-mirror_dir = data['external-mirror_dir']
local_data_dir = data['local_data_dir']
