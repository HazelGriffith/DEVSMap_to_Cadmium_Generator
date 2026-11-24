import re


# C++ types of the DEVSMap basic sets; any other set name (a struct) is its own C++ type
CPP_TYPES = {
    'floating_point': 'double',
    'integer': 'int',
    'unsigned_integer': 'unsigned int',
    'boolean': 'bool',
    'char': 'char',
    'string': 'std::string',
}

# A string literal, a number, an identifier, a two-character operator, whitespace, or any other character
TOKEN = re.compile(r'"(?:[^"\\]|\\.)*"|\d[\w.]*|[A-Za-z_]\w*|->|::|&&|\|\||[=!<>]=|\s+|.')


def cpp_type(domain):
    '''
    Returns the C++ type of a DEVSMap set name.

    Args:
        domain (str):   The set name of a port or state variable (for example "floating_point").
    '''
    return CPP_TYPES.get(domain, domain)


def translate_expression(expression, list_of_state_variables=()):
    '''
    Returns a DEVSMap expression in C++ syntax, where state variables become "state.variable"
    (whole names only, never inside a string literal or after ".", "->" or "::").

    Args:
        expression (str):                       The DEVSMap expression.
        list_of_state_variables (list):         The state variable names of the atomic model, if any.
    '''
    tokens = TOKEN.findall(expression)
    for i, token in enumerate(tokens):
        previous = neighbour(tokens, i, -1)
        if previous in ('.', '->', '::'):
            continue
        if token in list_of_state_variables:
            tokens[i] = 'state.' + token
    return ''.join(tokens)


def neighbour(tokens, i, step):
    '''
    Returns the nearest token before (step -1) or after (step 1) tokens[i] that is not whitespace.
    '''
    i += step
    while 0 <= i < len(tokens) and tokens[i].isspace():
        i += step
    return tokens[i] if 0 <= i < len(tokens) else None


def translate_map(data, list_of_state_variables):
    '''
    Returns a DEVSMap condition map (or the body of one of its branches) with every condition,
    assigned name and value translated to C++ by translate_expression().

    Args:
        data (dict):                            The DEVSMap dictionary to translate.
        list_of_state_variables (list):         The state variable names of the atomic model.
    '''
    return {
        key if key == 'otherwise' else translate_expression(key, list_of_state_variables):
        translate_map(value, list_of_state_variables) if isinstance(value, dict)
        else translate_expression(value, list_of_state_variables)
        for key, value in data.items()
    }


def build_conditional_statements(data, list_of_state_variables):
    '''
    Constructs and returns if-else statements from dictionaries where the keys are conditional 
    statements and the values are instructions to execute when the conditional statement is true.
    In Cadmium, this is used to generate the bodies of the internal transition function, external 
    transition function, confluent function, output function, etc.

    This function uses the translate_map() function to turn every condition and assignment into
    C++, with all state variables of the form "state.variable_name".

    Possible cases are listed below:

    1.  If the only key is "otherwise", and there is no data: The function in question is not implemented

    2.  If "otherwise" is the only key, this is the only statement to be executed, and the returned 
        statement will not be nested in an if-else structure.

    3.  If there are keys defined that are not called "otherwise", the if-else structure will be generated 
        via the build_conditional_statements_helper() function.

    Args:
        data (dict):                            The DEVSMap dictionary containing the conditions as keys, 
                                                and the execution instructions as values, to be converted 
                                                to an if-else C++ structure.
        list_of_state_variables (dict_items):   The list of state variables for the atomic model currently 
                                                being generated.  This is returned by atomic_model['s'].items().
    '''
    #print(data)
    #print(list_of_state_variables)
    data = translate_map(data, list_of_state_variables)
    conditional_statements = ''
    if len(data) == 1 and 'otherwise' in data:
        data = data['otherwise']
        if len(data) == 0:
            return '\t\t// Not implemented\n'
        for key in data:
            #print(key)
            #print(data)
            conditional_statements += simple_conditional_statement(key, data[key])
    else:
        conditional_statements = build_conditional_statements_helper(data)
    return conditional_statements


def simple_conditional_statement(key, value):
    '''
    Returns an assignment statement in C++ syntax that assigns value to a variable named key.

    Args:
        key (str):      The state variable being assigned.
        value (str):    The value to assign to the state variable.
    '''
    return '\t\t' + key + ' = ' + value + ';\n'


# Recursive function to write conditional blocks based on nested JSON structure
def build_conditional_statements_helper(data, indent=2):
    '''
    Helper function for build_conditional_statements().  This function generates the if-else 
    structures, and handles indentation.

    Args:
        data (dict):    The DEVSMap dictionary containing the conditions as keys, 
                        and the execution instructions as values, to be converted 
                        to an if-else C++ structure.
        indent (int):   The number of initial indentations.  In our case, the default is 2, 
                        because we assume in an atomic model we are working within a function 
                        (indent #1), that is within a class definition (indent #2).
    '''
    conditions = ''
    INDENT = "\t"  # Tab character used for indentation
    keys = list(data.keys())

    for i, key in enumerate(keys):
        value = data[key]
        is_last = (i == len(keys) - 1)
        is_otherwise = (key == "otherwise")

        # Write the condition header
        if is_otherwise:
            conditions += 'else {\n'  # Special case for "otherwise" treated as "else"
        elif i == 0:
            conditions += INDENT * indent + 'if (' + key + ') {\n'  # First condition: "if"
        else:
            conditions +='else if (' + key + ') {\n'  # Subsequent conditions: "else if"

        # Write the body of the block
        if isinstance(value, dict):
            # If all values are non-dictionaries, write assignments
            if all(not isinstance(v, dict) for v in value.values()):
                for var, expr in value.items():
                    conditions += INDENT * (indent + 1) + var + ' = ' + expr +';\n'
            else:
                # Otherwise, recursively handle nested conditions
                conditions += write_conditions(value, indent + 1)
        else:
            # Single assignment if value is not a dict
            conditions += INDENT * (indent + 1) + key + ' = ' + value + ';\n'

        # Write the block closing brace
        if i < len(keys) - 1:
            next_key = keys[i + 1]
            # If another block follows (assumed to be an "else"/"else if"), keep closing brace on same line
            if next_key == "otherwise" or True:  # Always true: forces inline formatting
                conditions += INDENT * indent + '} '
            else:
                conditions += INDENT * indent + '}\n'  # Default to newline
        else:
            # Last block: close normally
            conditions += INDENT * indent + '}\n'
            #Remove the else block if it is empty
            conditions = conditions.replace(' else {\n\t\t}\n', '\n')
            return conditions