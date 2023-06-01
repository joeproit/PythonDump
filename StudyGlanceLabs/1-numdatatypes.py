#1. Write a program to demonstrate different numerial data types in Python.
# Path: StudyGlanceLabs\1-numdatatypes.py
#JoeProIT 5/31/2023

# 1.Integer (int): Represents whole numbers without any decimal point, such as 0, 1, -5, 100.
# 2.Float (float): Represents decimal numbers with a fractional part, such as 3.14, -0.5, 2.0.
# 3.Complex (complex): Represents numbers with a real and imaginary part, such as 2+3j, -1+2j.
# 4.Boolean (bool): Represents a binary value, either True or False.
# 5.Long (long): Represents integers of unlimited size (Python 2 only).
# 6.Fraction (fractions.Fraction): Represents a fraction as a numerator and denominator, such as 1/2, 3/4.
# 7.Decimal (decimal.Decimal): Represents decimal numbers with arbitrary precision and fixed-point arithmetic, commonly used for financial and monetary calculations.

# 1.Integer (int)
# An integer is a whole number without any decimal point. There are three types of integers in Python: positive, negative, and zero.
# Positive integers are whole numbers greater than zero, such as 1, 2, 3, 4, 5, etc.
# Negative integers are whole numbers less than zero, such as -1, -2, -3, -4, -5, etc.
# Zero is neither positive nor negative. It is a whole number that represents the absence of quantity.

# 2.Float (float)
# A float is a decimal number with a fractional part. It is used to represent real numbers and is written with a decimal point dividing the integer and fractional parts.
# For example, 3.14, 0.5, 2.0, -1.5, 0.0, etc., are float numbers.

# 3.Complex (complex)
# A complex number is a number with a real and imaginary part. It is written as x + yj, where x is the real part and y is the imaginary part.
# For example, 2+3j, -1+2j, 0+0j, etc., are complex numbers.

# 4.Boolean (bool)
# A Boolean value is either True or False. It is used to represent the truth value of an expression.
# For example, 2 + 2 == 4 evaluates to True, whereas 2 + 2 == 5 evaluates to False.

# 5.Long (long)
# A long integer is an integer of unlimited size. It is written as a series of digits followed by the letter L.
# For example, 1234567890987654321L is a long integer.

# 6.Fraction (fractions.Fraction)
# A fraction is a rational number represented as a pair of integers: a numerator and a denominator.
# For example, 1/2, 3/4, 2/5, etc., are fractions.

# 7.Decimal (decimal.Decimal)
# A decimal number is a number with a decimal point. It is used to represent real numbers with arbitrary precision.
# For example, 0.5, 3.14, 0.0001, 0.00000000000

# A function that incorporates all the above data types
def numdatatypes():
    print("Integer: ", 10)
    print("Float: ", 10.5)
    print("Complex: ", 1 + 3j)
    print("Boolean: ", True)
    print("Long: ", 1234567890987654321)
    print("Fraction: ", 1 / 2)
    print("Decimal: ", 0.000)
numdatatypes()

# Output:
# Integer:  10
# Float:  10.5
# Complex:  (1+3j)
# Boolean:  True
# Long:  1234567890987654321
# Fraction:  0.5
# Decimal:  0.0



