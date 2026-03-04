#!/usr/bin/env python3

tasks = []

def add_task(task):
    tasks.append(task)

def remove_task(index):
    if 0 <= index < len(tasks):
        del tasks[index]

def list_tasks():
    for i, task in enumerate(tasks):
        print(f'{i}: {task}')