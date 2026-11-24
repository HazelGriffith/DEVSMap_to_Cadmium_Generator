import re

from generate_simple_statements import infinity


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

# Operators that bind looser than "+", so they end a string concatenation
CONCATENATION_BOUNDARIES = {',', ';', '=', '==', '!=', '<', '>', '<=', '>=', '&&', '||', '?', ':', '!'}


def cpp_type(domain):
    '''
    Returns the C++ type of a DEVSMap set name.

    Args:
        domain (str):   The set name of a port or state variable (for example "floating_point").
    '''
    return CPP_TYPES.get(domain, domain)


def translate_expression(expression, list_of_state_variables=()):
    '''
    Returns a DEVSMap expression in C++ syntax:
    - state variables become "state.variable" (whole names only, never inside a string literal
      or after ".", "->" or "::"),
    - inf and nan become std::numeric_limits values,
    - an array literal [a, b, c] becomes a pointer to its elements, as C++ array parameters expect,
    - "text" + x + ... becomes a std::string concatenation with std::to_string(x).

    Args:
        expression (str):                       The DEVSMap expression.
        list_of_state_variables (list):         The state variable names of the atomic model, if any.
    '''
    tokens = concatenate_strings(TOKEN.findall(expression))
    for i, token in enumerate(tokens):
        previous = neighbour(tokens, i, -1)
        if previous in ('.', '->', '::'):
            continue
        if token in list_of_state_variables:
            tokens[i] = 'state.' + token
        elif token == 'inf':
            tokens[i] = infinity()
        elif token == 'nan':
            tokens[i] = 'std::numeric_limits<double>::quiet_NaN()'
        elif token == '[':
            tokens[i] = 'std::array{'
        elif token == ']':
            tokens[i] = '}.data()'
    return ''.join(tokens)


def neighbour(tokens, i, step):
    '''
    Returns the nearest token before (step -1) or after (step 1) tokens[i] that is not whitespace.
    '''
    i += step
    while 0 <= i < len(tokens) and tokens[i].isspace():
        i += step
    return tokens[i] if 0 <= i < len(tokens) else None


def concatenate_strings(tokens):
    '''
    Returns tokens with each chain of "+" operands that holds a string literal rewritten as a
    std::string concatenation: std::string("text") + std::to_string(x) + "s".

    Args:
        tokens (list):  The tokens of one expression.
    '''
    i = 0
    while i < len(tokens):
        if tokens[i].startswith('"') and '+' in (neighbour(tokens, i, -1), neighbour(tokens, i, 1)):
            start, end = concatenation_bounds(tokens, i)
            joined = []
            for k, operand in enumerate(split_operands(tokens[start:end])):
                if k > 0:
                    joined += [' ', '+', ' ']
                if len(operand) != 1 or not operand[0].startswith('"'):
                    joined += ['std::to_string(', *operand, ')']
                elif k == 0:
                    joined += ['std::string(', *operand, ')']
                else:
                    joined += operand
            tokens[start:end] = joined
            i = start + len(joined)
        else:
            i += 1
    return tokens


def concatenation_bounds(tokens, i):
    '''
    Returns (start, end) of the "+" chain that holds tokens[i], at the bracket depth of tokens[i].
    '''
    bounds = []
    for step, opening, closing in ((-1, {')', ']'}, {'(', '['}), (1, {'(', '['}, {')', ']'})):
        depth, j = 0, i
        while 0 <= j + step < len(tokens):
            token = tokens[j + step]
            if token in opening:
                depth += 1
            elif token in closing:
                if depth == 0:
                    break
                depth -= 1
            elif depth == 0 and token in CONCATENATION_BOUNDARIES:
                break
            j += step
        while tokens[j].isspace():
            j -= step
        bounds.append(j)
    return bounds[0], bounds[1] + 1


def split_operands(tokens):
    '''
    Returns the operands of a "+" chain, each a list of tokens without surrounding whitespace.
    '''
    operands, depth = [[]], 0
    for token in tokens:
        if token in ('(', '['):
            depth += 1
        elif token in (')', ']'):
            depth -= 1
        if token == '+' and depth == 0:
            operands.append([])
        else:
            operands[-1].append(token)
    for operand in operands:
        while operand and operand[0].isspace():
            operand.pop(0)
        while operand and operand[-1].isspace():
            operand.pop()
    return operands


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
        translate_value(value, list_of_state_variables)
        for key, value in data.items()
    }


def translate_value(value, list_of_state_variables):
    '''
    Returns a value of a DEVSMap condition map translated to C++: a nested map by translate_map(),
    a list (several messages on one output port) element by element, and an expression by
    translate_expression().

    Args:
        value (dict, list or str):              The DEVSMap value to translate.
        list_of_state_variables (list):         The state variable names of the atomic model.
    '''
    if isinstance(value, dict):
        return translate_map(value, list_of_state_variables)
    if isinstance(value, list):
        return [translate_expression(element, list_of_state_variables) for element in value]
    return translate_expression(value, list_of_state_variables)


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


def simple_conditional_statement(key, value, indent=2):
    '''
    Returns an assignment statement in C++ syntax that assigns value to a variable named key.
    A list value (several messages on one output port) gives one statement per element, in order.

    Args:
        key (str):              The state variable being assigned.
        value (str or list):    The value to assign to the state variable.
        indent (int):           The number of indentations.
    '''
    values = value if isinstance(value, list) else [value]
    return ''.join('\t' * indent + key + ' = ' + element + ';\n' for element in values)


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
                    conditions += simple_conditional_statement(var, expr, indent + 1)
            else:
                # Otherwise, recursively handle nested conditions
                conditions += write_conditions(value, indent + 1)
        else:
            # Single assignment if value is not a dict
            conditions += simple_conditional_statement(key, value, indent + 1)

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