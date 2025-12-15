
def dump_32bithex(f, data):
    if (len(data) & 3) != 0: #Is not 4-aligned
        fill_to_4align = ((len(data) + 3) & ~3) - len(data)
        data = bytearray(data) + bytearray([0] * fill_to_4align)
    for i in range(0, len(data), 4):
        word = data[i:i+4]
        f.write('%02x%02x%02x%02x\n' % (word[3], word[2], word[1], word[0]))

def test_envarg_true(env, argname):
    if not (argname in env):
        return False
    argval = env[argname]
    try:
        return argval.lower() == "true" or int(argval) > 0
    except ValueError:
        return False #not an int

def get_envarg_or(env, argname, default):
    if not (argname in env):
        return default
    return env[argname]
