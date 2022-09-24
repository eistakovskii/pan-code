#!/usr/bin/env python3

import argparse
from os.path import exists
from glob import glob
from os.path import isdir
from sklearn.metrics import balanced_accuracy_score
import json

def error(msg):
    print('  [\033[91mx\033[0m] ' + msg)
    exit(1)

def success(msg):
    print('  [\033[92mo\033[0m] ' + msg)

def load_json_lines(f):
    if not exists(f):
        error('The file "' + f + '" does not exist.')

    ret = []
    num = 1
    
    if isdir(f):
        f = glob(f + '/*.json*')
        
        if len(f) != 1:
            error('The input is an directory that contains multiple json files. Please create only a single json file. Got ' + str(f))
        
        f = f[0]
    
    with open(f, 'r') as inp:
        for l in inp:
            try:
                ret += [json.loads(l)]
            except:
                error('Invalid line ' + str(num) + ' in "' + f + '" with content: ' + l.strip())
            num += 1

    success('The file ' + f + ' is in JSONL format.')
    return ret

def spoiler_predictions_to_map(l, error=error, field='spoilerType'):
    if l is None or len(l) == 0:
        error('Spoiler predictions are empty.')
    uuids = []

    for i in l:
        if 'uuid' not in i.keys() or field not in i.keys():
            error(f'Spoiler predictions do not have all required fields. Expected fields "uuid" and "{field}". Got: ' + str(i))
            return
        uuids += [i['uuid']]

    if len(l) != len(set(uuids)):
            error('Spoiler predictions have dupliates. I found ' + str(len(l)) + ' entries but only ' + str(len(set(uuids))) + ' unique uuids.')
            return

    success('Spoiler predictions have correct format. Found ' + str(len(l)))
    return {i['uuid']: i[field] if type(i[field]) is not list else i[field][0] for i in l}

def normalize_spoiler_generation(i, error):
    if 'uuid' not in i or 'spoiler' not in i:
        error('Spoiler generation does not have all required fields. Expected fields are uuid and spoiler. Got: ' + str(i))
        return

    return {i['uuid']: i['spoiler']}

def spoiler_generations_to_map(l, error=error):
    if l is None or len(l) == 0:
        error('Spoiler predictions are empty.')
    uuids = []

    for i in l:
        i = normalize_spoiler_generation(i, error)
        if not i:
            return
        uuids += list(i.keys())

    if len(l) != len(set(uuids)):
            error('Spoiler generations have dupliates. I found ' + str(len(l)) + ' entries but only ' + str(len(set(uuids))) + ' unique uuids.')

    l = [normalize_spoiler_generation(i, error) for i in l]

    success('Spoiler generations have correct format. Found ' + str(len(l)))
    ret = {}
    for i in l:
        for k, v in i.items():
            assert k not in ret
            ret[k] = v
    
    return ret


def parse_args():
    parser = argparse.ArgumentParser(description='Evaluate submissions to the clickbait spoiling task.')

    parser.add_argument('--input_run', type=str, help='The input run (expected in jsonl format) produced by a system that should be evaluated.', required=True)
    parser.add_argument('--ground_truth_classes', type=str, help='The ground truth classes used to evaluate submissions to task 1 (spoiler type generation). For the evaluation of task 2 (spoiler generation), this can be different from "--ground_truth_spoilers" to evaluate the effectiveness using real spoiler predictions.', required=False)
    parser.add_argument('--ground_truth_spoilers', type=str, help='The ground truth spoilers used to evaluate submissions to task 2 (spoiler generation).', required=False)
    parser.add_argument('--task', type=str, help='The task to evaluate. Choose 1 (spoiler type classification) or 2 (spoiler generation).', choices=['1', '2'], required=True)
    parser.add_argument('--output_prototext', type=str, help='Write evalualuation results as prototext file to this location.', required=False)


    return parser.parse_args()

def to_prototext(d):
    ret = ''
    
    for k, v in d.items():
        ret += 'measure{\n  key: "' + str(k) + '"\n  value: "' + str(v) + '"\n}\n'
    
    return ret.strip()

def create_protobuf_for_task_1(actual, expected):
    keys = sorted(actual.keys())
    missing_predictions = 0
    
    y_true = []
    y_pred = []
    
    for k in keys:
        y_true += [expected[k]]
        
        if k in actual:
            y_pred += [actual[k]]
        else:
            missing_predictions += 1
            y_pred += ['']
    
    balanced_accuracy_score

    return to_prototext({
        "result-size": len(keys),
        'balanced-accuracy': balanced_accuracy_score(y_true, y_pred),
        'missing_predictions': missing_predictions
    })

def eval_task_1(input_run, ground_truth_classes, output_file):
    input_run = spoiler_predictions_to_map(input_run)
    ret = None
    if ground_truth_spoilers == None:
        success('No ground-truth is passed. I tested the input run and the input run is valid.')
        ret = to_prototext({"result-size": len(input_run.keys())})
        
    else:
        ground_truth_spoilers = spoiler_predictions_to_map(ground_truth_spoilers, field='tags')
        ret = create_protobuf_for_task_1(input_run, ground_truth_spoilers)

    if output_file:
        with open(output_file, 'w') as f:
            f.write(ret)

def eval_task_2(input_run, ground_truth_classes, ground_truth_spoilers):
    input_run = spoiler_generations_to_map(input_run)
    if ground_truth_spoilers == None:
        success('No ground-truth is passed. I tested the input run and the input run is valid.')
    else:
        error('ToDo: The evaluator currently only checks if the format is valid')

if __name__ == '__main__':
    args = parse_args()
    input_run = load_json_lines(args.input_run)
    ground_truth_classes = None if not args.ground_truth_classes else load_json_lines(args.ground_truth_classes)
    ground_truth_spoilers = None if not args.ground_truth_spoilers else load_json_lines(args.ground_truth_spoilers)

    if args.task == '1':
        eval_task_1(input_run, ground_truth_classes, args.output_prototext)
    elif args.task == '2':
        eval_task_2(input_run, ground_truth_classes, ground_truth_spoilers)
    else:
        error('Unknown task. Expected 1 or 2. Got: ' + str(args.task))

