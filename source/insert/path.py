import sys
import yaml

with open('user-config.yaml', 'r') as stream:
    data = yaml.load(stream, Loader=yaml.FullLoader)

sys.path.append('{}/source/clean'.format(data['base_dir']))
sys.path.append('{}/source/insert'.format(data['base_dir']))
sys.path.append(data['diarios_dir'])

data_dir = data['data_dir']
