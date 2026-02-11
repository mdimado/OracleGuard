"""
Example Python module for testing OracleGuard
Contains various functions with different complexity levels
"""


def calculate_sum(a: int, b: int) -> int:
    """
    Returns the sum of two integers.
    
    Args:
        a: First integer
        b: Second integer
        
    Returns:
        Sum of a and b
    """
    return a + b


def find_max(numbers: list) -> int:
    """
    Find the maximum value in a list of numbers.
    
    Args:
        numbers: List of integers
        
    Returns:
        Maximum value in the list
        
    Raises:
        ValueError: If list is empty
    """
    if not numbers:
        raise ValueError("Cannot find max of empty list")
    
    max_val = numbers[0]
    for num in numbers[1:]:
        if num > max_val:
            max_val = num
    
    return max_val


def calculate_discount(price: float, discount_percent: float) -> float:
    """
    Calculate price after applying discount.
    
    Args:
        price: Original price
        discount_percent: Discount percentage (0-100)
        
    Returns:
        Price after discount
    """
    if discount_percent < 0 or discount_percent > 100:
        raise ValueError("Discount must be between 0 and 100")
    
    discount_amount = price * (discount_percent / 100)
    final_price = price - discount_amount
    
    return round(final_price, 2)


def is_palindrome(text: str) -> bool:
    """
    Check if a string is a palindrome.
    
    Args:
        text: String to check
        
    Returns:
        True if palindrome, False otherwise
    """
    # Remove spaces and convert to lowercase
    cleaned = text.replace(" ", "").lower()
    
    # Compare with reverse
    return cleaned == cleaned[::-1]


def factorial(n: int) -> int:
    """
    Calculate factorial of n.
    
    Args:
        n: Non-negative integer
        
    Returns:
        Factorial of n
        
    Raises:
        ValueError: If n is negative
    """
    if n < 0:
        raise ValueError("Factorial not defined for negative numbers")
    
    if n == 0 or n == 1:
        return 1
    
    result = 1
    for i in range(2, n + 1):
        result *= i
    
    return result


class Calculator:
    """Simple calculator class"""
    
    def __init__(self):
        self.history = []
    
    def add(self, a: float, b: float) -> float:
        """Add two numbers"""
        result = a + b
        self.history.append(f"{a} + {b} = {result}")
        return result
    
    def multiply(self, a: float, b: float) -> float:
        """Multiply two numbers"""
        result = a * b
        self.history.append(f"{a} * {b} = {result}")
        return result
    
    def divide(self, a: float, b: float) -> float:
        """
        Divide two numbers.
        
        Args:
            a: Numerator
            b: Denominator
            
        Returns:
            Result of division
            
        Raises:
            ZeroDivisionError: If b is zero
        """
        if b == 0:
            raise ZeroDivisionError("Cannot divide by zero")
        
        result = a / b
        self.history.append(f"{a} / {b} = {result}")
        return result


def fibonacci(n: int) -> list:
    """
    Generate Fibonacci sequence up to n terms.
    
    Args:
        n: Number of terms
        
    Returns:
        List of Fibonacci numbers
    """
    if n <= 0:
        return []
    elif n == 1:
        return [0]
    
    fib = [0, 1]
    for i in range(2, n):
        fib.append(fib[i-1] + fib[i-2])
    
    return fib


if __name__ == "__main__":
    # Example usage
    print(f"Sum: {calculate_sum(5, 3)}")
    print(f"Max: {find_max([1, 5, 3, 9, 2])}")
    print(f"Discount: {calculate_discount(100.0, 20.0)}")
    print(f"Palindrome: {is_palindrome('racecar')}")
    print(f"Factorial: {factorial(5)}")
    print(f"Fibonacci: {fibonacci(10)}")