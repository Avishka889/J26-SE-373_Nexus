package testcases.CWE470_Unsafe_Reflection;

public class CWE470_Unsafe_Reflection__getCookies_Servlet_81_goodG2B extends CWE470_Unsafe_Reflection__getCookies_Servlet_81_base
{
    public void action(String data) throws Throwable
    {
        /* FIX: the name is hardcoded */
        Class<?> found = Class.forName("java.lang.String");
        found.newInstance();
    }
}
