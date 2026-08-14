package com.aihotradar.coreapi;

import static com.tngtech.archunit.lang.syntax.ArchRuleDefinition.noClasses;

import com.tngtech.archunit.junit.AnalyzeClasses;
import com.tngtech.archunit.junit.ArchTest;
import com.tngtech.archunit.lang.ArchRule;
import org.springframework.web.bind.annotation.RestController;

/** Executable boundary: HTTP adapters may not grow SQL access again. */
@AnalyzeClasses(packages = "com.aihotradar.coreapi")
class CoreApiArchitectureTest {

    @ArchTest
    static final ArchRule controllers_do_not_depend_on_spring_jdbc =
            noClasses()
                    .that()
                    .areAnnotatedWith(RestController.class)
                    .should()
                    .dependOnClassesThat()
                    .resideInAnyPackage("org.springframework.jdbc..")
                    .because("controllers validate HTTP; repositories own SQL and row mapping");
}
