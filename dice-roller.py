import random

def roll_dice(num_dice, num_sides):
    total = 0
    rolls = []
    for _ in range(num_dice):
        roll = random.randint(1, num_sides)
        total += roll
        rolls.append(roll)
    return total, rolls

def main():
    print("DND Dice Roller")
    print("----------------")
    print("Enter the number of dice and the number of sides for each dice.")

    num_dice = int(input("Number of dice: "))
    num_sides = int(input("Number of sides: "))

    total, rolls = roll_dice(num_dice, num_sides)

    print("\nDice Rolls:")
    for index, roll in enumerate(rolls):
        print(f"Die {index+1}: {roll}")
    print("----------------")
    print(f"Total: {total}")

if __name__ == '__main__':
    main()
