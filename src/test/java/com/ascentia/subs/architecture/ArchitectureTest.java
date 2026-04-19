package com.ascentia.subs.architecture;

import com.tngtech.archunit.junit.AnalyzeClasses;
import com.tngtech.archunit.junit.ArchTest;
import com.tngtech.archunit.lang.syntax.ArchRuleDefinition;
import com.tngtech.archunit.lang.ArchRule;
import com.tngtech.archunit.core.importer.ImportOption;
import org.springframework.context.annotation.Configuration;
import org.springframework.stereotype.Service;
import org.springframework.web.bind.annotation.RestController;

@AnalyzeClasses(packages = "com.ascentia.subs", importOptions = ImportOption.DoNotIncludeTests.class)
class ArchitectureTest {

    @ArchTest
    static final ArchRule controllersShouldResideInFeaturePackages =
            ArchRuleDefinition.classes()
                    .that().areAnnotatedWith(RestController.class)
                    .should().resideInAnyPackage("..auth..", "..history..", "..jobs..", "..web..");

    @ArchTest
    static final ArchRule configurationShouldStayInConfigPackage =
            ArchRuleDefinition.classes()
                    .that().areAnnotatedWith(Configuration.class)
                    .should().resideInAPackage("..config..");

    @ArchTest
    static final ArchRule storesShouldRemainFeatureScopedServices =
            ArchRuleDefinition.classes()
                    .that().haveSimpleNameEndingWith("Store")
                    .and().areAnnotatedWith(Service.class)
                    .should().resideInAnyPackage("..auth..", "..history..", "..jobs..", "..points..", "..usage..");

    @ArchTest
    static final ArchRule configShouldNotDependOnBusinessStores =
            ArchRuleDefinition.noClasses()
                    .that().resideInAPackage("..config..")
                    .should().dependOnClassesThat()
                    .resideInAnyPackage("..history..", "..jobs..", "..points..", "..usage..");
}
