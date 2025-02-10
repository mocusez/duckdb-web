import os
import sys
import re
import subprocess
import csv
import io


def run_duckdb_script(cmd):
    # we pass /dev/null to the initialization script to skip reading `~/.duckdbrc`
    res = subprocess.run(
        [db_path, "-init", "/dev/null"],
        input=bytearray(cmd, 'utf8'),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout = res.stdout.decode('utf8').strip()
    stderr = res.stderr.decode('utf8').strip()

    if len(stderr) != 0:
        print("Failed to run command " + cmd)
        print(stdout)
        print(stderr)
        exit(1)

    return stdout


if len(sys.argv) < 2:
    print(
        "Expected usage: python3 scripts/generate_config_docs.py /path/to/duckdb/binary"
    )
    exit(1)

db_path = sys.argv[1]

keywords = [
    'STANDARD',
    'DETAILED',
    'ALL',
    'OPTIMIZED_ONLY',
    'PHYSICAL_ONLY',
    'JSON',
    'QUERY_TREE',
    'ASC',
    'DESC',
    'NULLS_FIRST',
    'NULLS_LAST',
    'AUTOMATIC',
    'READ_ONLY',
    'READ_WRITE',
    'PARTITION_BY',
]

description_replacement = "description.replace('e.g. ', 'e.g., ')"
for keyword in keywords:
    description_replacement += f".replace('{keyword}', '`{keyword}`')"

script = f'''
.mode markdown
INSTALL httpfs;
LOAD httpfs;
CREATE MACRO surround_with_backticks(str) AS '`' || str || '`';
CREATE TABLE configurations AS SELECT
    substr(name, 2, (LEN(name) - 2)::int) AS Name,
    {description_replacement} AS Description,
    surround_with_backticks(input_type) AS "Type",
    default_value AS "Default value",
    scope AS "Scope"
FROM (
    SELECT array_agg(surround_with_backticks(name))::VARCHAR AS name, description, input_type,
        first(CASE
        WHEN value = ''
        THEN ''
        WHEN name = 'enable_progress_bar'
        THEN surround_with_backticks('true')
        WHEN name='memory_limit' OR name='max_memory'
        THEN '80% of RAM'
        WHEN name='secret_directory'
        THEN '`' || regexp_replace(value, '/(home|Users)/[a-z][-a-z0-9_]*/', '~/') || '`'
        WHEN name='threads' OR name='worker_threads'
        THEN '# CPU cores'
        WHEN name='TimeZone'
        THEN 'System (locale) timezone'
        WHEN name='Calendar'
        THEN 'System (locale) calendar'
        WHEN lower(value) IN ('null', 'nulls_last', 'asc', 'desc')
        THEN surround_with_backticks(upper(value))
        WHEN name='temp_directory'
        THEN '`⟨database_name⟩.tmp` or `.tmp` (in in-memory mode)'
        ELSE surround_with_backticks(value) END) AS default_value,
        scope
    FROM duckdb_settings()
    WHERE name NOT LIKE '%debug%' AND description NOT ILIKE '%debug%'
    GROUP BY description, input_type, scope
) tbl
ORDER BY 1
;
'''

get_global_flags = '''
SELECT * EXCLUDE Scope
FROM configurations
WHERE Scope = 'GLOBAL';
'''

get_local_flags = '''
SELECT * EXCLUDE Scope
FROM configurations
WHERE Scope = 'LOCAL';
'''

global_configuration_flags = run_duckdb_script(script + get_global_flags)

local_config_script = script + get_local_flags

local_configuration_flags = run_duckdb_script(local_config_script)

option_split = '## Configuration Reference'
doc_file = 'docs/configuration/overview.md'

with open(doc_file, 'r') as f:
    text = f.read()

if option_split not in text:
    print("Could not find " + option_split)
    exit(1)

text = text.split(option_split)[0]

text += (
    option_split
    + "\n\n<!-- This section is generated by scripts/generate_config_docs.py -->\n\n"
    + "Configuration options come with different default [scopes]({% link docs/sql/statements/set.md %}#scopes): `GLOBAL` and `LOCAL`. "
    + "Below is a list of all available configuration options by scope.\n"
)

text += '\n### Global Configuration Options\n\n' + global_configuration_flags + '\n'
text += '\n### Local Configuration Options\n\n' + local_configuration_flags + '\n'
text = re.sub(
    r'^\|---*\|---*\|---*\|---*\|$', '|----|--------|--|---|', text, flags=re.MULTILINE
)
text = text.replace('`QUERY_TREE`_OPTIMIZER', '`QUERY_TREE_OPTIMIZER`')

with open(doc_file, 'w+') as f:
    f.write(text)
