# 2. #Write a program to demonstrate different string data types in Python.
# Path: StudyGlanceLabs\2-stringdatatypes.py
# JoeProIT 5/31/2023

# A function that incorporates all the above data types
def stringdatatypes():
    print("String: ", "hello")
    print("Byte: ", b"hello")
    print("Byte Array: ", bytearray(b"hello"))
    print("Raw String: ", r"hello \n world")
    print("Unicode: ", u"hello world")
stringdatatypes()

# Output:
# String:  hello
# Byte:  b'hello'
# Byte Array:  bytearray(b'hello')
# Raw String:  hello \n world
# Unicode:  hello world

# 1.String (str): Represents a sequence of Unicode characters, such as "hello", 'hello world', etc.
# 2.Byte (bytes): Represents a sequence of bytes, such as [116, 101, 115, 116].
# 3.Byte Array (bytearray): Represents a mutable sequence of bytes, such as [116, 101, 115, 116].
# 4.Raw String (r): Represents a raw string, such as r"hello \n world".
# 5.Unicode (u): Represents a Unicode string, such as u"hello world".

# Some additional string data types are:
# 6. F-strings (Formatted string literals): Introduced in Python 3.6, f-strings provide a concise and convenient way to embed expressions inside string literals. They are prefixed with the letter f and allow you to include variable values directly within the string using curly braces {}. For example, f"Hello {name}".
# 7. String Template (string.Template): Introduced in Python 2.4, string templates provide simpler string substitutions as described in PEP 292. They are prefixed with the letter T and allow you to include variable values within the string using placeholders $var. For example, T"Hello $name".
# 8. Mutable String (str): Introduced in Python 3.9, mutable strings are a new type of string that is mutable and can be modified in-place. They are prefixed with the letter m and allow you to modify the string in-place using the same methods as byte arrays. For example, m"Hello world".
# 9. Unicode Escape Sequences: Unicode escape sequences are used to represent Unicode characters using ASCII characters. They are prefixed with the letter u and allow you to include Unicode characters within the string using the \uXXXX escape sequence. For example, u"\u00C6".

